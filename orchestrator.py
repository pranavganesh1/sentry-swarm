from __future__ import annotations

import json
import logging
import queue
import threading
import time
from collections.abc import Callable
from datetime import datetime
from typing import TYPE_CHECKING, Any, Union

import dashboard_rich as dash
from commands import get_pending_commands, mark_processed
from metrics import get_summary, record_incident
from state import IncidentState

if TYPE_CHECKING:
    from agents.sentry import SentryTrigger, PhysicalTrigger


logger = logging.getLogger("orchestrator")

MAX_CONCURRENT_INCIDENTS = 3
AGENT_TIMEOUT_SECONDS = 120
STUCK_INCIDENT_THRESHOLD_SECONDS = 180  # force-close anything active longer than this


ACTIVE_SNAPSHOT_FILE = "logs/active_incidents.json"


class IncidentOrchestrator:
    """Orchestrates the incident response pipeline, managing agents, workers, and incident lifecycle."""
    def __init__(
        self,
        *,
        sentry: Any | None = None,
        diagnostician: Any | None = None,
        fix_planner: Any | None = None,
        comms: Any | None = None,
        agent_timeout_seconds: float = AGENT_TIMEOUT_SECONDS,
    ):
        """Initialize the orchestrator with agents and configuration."""
        self._queue: queue.Queue[Union[SentryTrigger, PhysicalTrigger] | None] = queue.Queue()
        self._active: dict[str, IncidentState] = {}
        self._known_ids: set[str] = set()
        self._known_types: set[str] = set()
        self._lock = threading.RLock()
        self._running = threading.Event()
        self._workers: list[threading.Thread] = []
        self._sentry_thread: threading.Thread | None = None
        self._agent_timeout_seconds = agent_timeout_seconds
        self._pipeline_semaphore = threading.Semaphore(MAX_CONCURRENT_INCIDENTS)

        if sentry is None:
            from agents.sentry import SentryAgent

            sentry = SentryAgent(on_incident=self._enqueue)
        else:
            sentry.on_incident = self._enqueue
        self.sentry = sentry

        if diagnostician is None:
            from agents.diagnostician import DiagnosticianAgent

            diagnostician = DiagnosticianAgent()
        self.diagnostician = diagnostician

        if fix_planner is None:
            from agents.fix_planner import FixPlannerAgent

            fix_planner = FixPlannerAgent()
        self.fix_planner = fix_planner

        if comms is None:
            from agents.comms import CommsAgent

            comms = CommsAgent()
        self.comms = comms

        self.on_state_update: Callable[[IncidentState], None] | None = None
        self.on_incident_done: Callable[[IncidentState], None] | None = None

    def start(self) -> None:
        """Start the orchestrator, launching sentry, worker, watchdog, and command threads."""
        if self._running.is_set():
            logger.warning("[orchestrator] Start ignored; already running")
            return

        self._running.set()
        logger.info("[orchestrator] Starting")

        self._sentry_thread = threading.Thread(
            target=self.sentry.start,
            name="sentry",
            daemon=True,
        )
        self._sentry_thread.start()

        self._workers = [
            threading.Thread(
                target=self._worker_loop,
                name=f"orchestrator-worker-{index + 1}",
                daemon=True,
            )
            for index in range(MAX_CONCURRENT_INCIDENTS)
        ]
        for worker in self._workers:
            worker.start()

        self._watchdog_thread = threading.Thread(
            target=self._watchdog_loop,
            name="orchestrator-watchdog",
            daemon=True,
        )
        self._watchdog_thread.start()

        self._command_thread = threading.Thread(
            target=self._command_loop,
            name="orchestrator-commands",
            daemon=True,
        )
        self._command_thread.start()

        logger.info(
            "[orchestrator] Running with %d incident workers, watchdog active, commands active",
            MAX_CONCURRENT_INCIDENTS,
        )

    def stop(self, join_timeout: float = 5.0) -> None:
        """Stop the orchestrator, stopping the sentry and waiting for workers to finish."""
        if not self._running.is_set():
            return

        self._running.clear()
        self.sentry.stop()
        for _ in self._workers:
            self._queue.put(None)
        for worker in self._workers:
            worker.join(timeout=join_timeout)
        if self._sentry_thread:
            self._sentry_thread.join(timeout=join_timeout)
        logger.info("[orchestrator] Stopped")

    def get_active_incidents(self) -> list[IncidentState]:
        with self._lock:
            return list(self._active.values())

    def get_incident_by_id(self, incident_id: str) -> IncidentState | None:
        with self._lock:
            return self._active.get(incident_id)

    def manually_resolve(self, incident_id: str, reason: str = "Manually resolved") -> bool:
        with self._lock:
            state = self._active.get(incident_id)
            if not state:
                logger.warning("[orchestrator] No active incident with id %s", incident_id)
                return False
            state.status = "resolved"
            state.comms_update = f"Manually resolved: {reason}"

        record_incident(state)
        self.sentry.clear_incident(state.incident_type)
        with self._lock:
            self._active.pop(incident_id, None)
            self._known_ids.discard(incident_id)
            self._known_types.discard(state.incident_type)
        logger.info("[orchestrator] Incident %s manually resolved: %s", incident_id, reason)
        self._write_active_snapshot()
        return True

    def get_metrics(self) -> dict:
        return get_summary()

    def inject_incident(self, trigger: SentryTrigger) -> bool:
        logger.info(
            "[orchestrator] Manual inject: %s", trigger.incident_type
        )
        return self._enqueue(trigger)

    def _enqueue(self, trigger: Union[SentryTrigger, PhysicalTrigger]) -> bool:
        with self._lock:
            if trigger.incident_id in self._known_ids:
                logger.warning(
                    "[orchestrator] Duplicate incident ID ignored: %s",
                    trigger.incident_id,
                )
                return False
            if trigger.incident_type in self._known_types:
                logger.warning(
                    "[orchestrator] Incident type already queued or active: %s",
                    trigger.incident_type,
                )
                return False
            self._known_ids.add(trigger.incident_id)
            self._known_types.add(trigger.incident_type)

        self._queue.put(trigger)
        logger.info(
            "[orchestrator] Queued incident %s (%s)",
            trigger.incident_id,
            trigger.incident_type,
        )
        return True

    def _worker_loop(self) -> None:
        while True:
            try:
                trigger = self._queue.get(timeout=0.5)
            except queue.Empty:
                if not self._running.is_set():
                    return
                continue

            try:
                if trigger is None:
                    return
                self._run_pipeline(trigger)
            finally:
                self._queue.task_done()

    def _run_pipeline(self, trigger: SentryTrigger) -> None:
        incident_id = trigger.incident_id

        acquired = self._pipeline_semaphore.acquire(timeout=30)
        if not acquired:
            logger.error(
                "[orchestrator] Could not acquire pipeline slot for %s — system overloaded",
                incident_id,
            )
            return

        try:
            self._run_pipeline_inner(trigger)
        finally:
            self._pipeline_semaphore.release()

    def _run_pipeline_inner(self, trigger: SentryTrigger) -> None:
        """Run the incident processing pipeline for a single trigger."""
        incident_id = trigger.incident_id
        state = self._initial_state(trigger)
        self._store_and_emit(state)
        logger.info(
            "[orchestrator] Pipeline started for %s (%s)",
            incident_id,
            trigger.incident_type,
        )

        dash.open_incident(state)

        try:
            # ── Diagnostician ─────────────────────────────────────────
            dash.update_incident_step(incident_id, "diagnostician")
            state = self._run_step(
                "diagnostician",
                incident_id,
                lambda: self.diagnostician.run(trigger),
            )
            dash.update_incident_step(incident_id, "diagnostician", done=True)
            self._store_and_emit(state)

            # ── Fix-Planner ───────────────────────────────────────────
            dash.update_incident_step(incident_id, "fix_planner")
            state = self._run_step(
                "fix_planner",
                incident_id,
                lambda: self.fix_planner.run(state),
            )
            dash.update_incident_step(incident_id, "fix_planner", done=True)
            self._store_and_emit(state)

            # ── Comms ─────────────────────────────────────────────────
            dash.update_incident_step(incident_id, "comms")
            state = self._run_step(
                "comms",
                incident_id,
                lambda: self.comms.run(state),
            )
            dash.update_incident_step(incident_id, "comms", done=True)
            state.status = "resolved"
            self._store_and_emit(state)
        except Exception as error:
            logger.exception(
                "[orchestrator] Pipeline failed for %s: %s",
                incident_id,
                error,
            )
            state.status = "error"
            self._store_and_emit(state)
        finally:
            self._finish_incident(trigger, state)
            if state.status == "resolved":
                dash.close_incident(state)

    def _initial_state(self, trigger: SentryTrigger) -> IncidentState:
        return IncidentState(
            incident_id=trigger.incident_id,
            incident_type=trigger.incident_type,
            severity=trigger.severity,
            affected_services=list(trigger.affected_services),
            trigger_events=list(trigger.trigger_events),
            started_at=trigger.started_at,
            detected_at=trigger.detected_at,
            mttd_seconds=max(
                0.0, (trigger.detected_at - trigger.started_at).total_seconds()
            ),
            status="active",
        )

    def _run_step(
        self,
        step_name: str,
        incident_id: str,
        function: Callable[[], IncidentState],
    ) -> IncidentState:
        logger.info(
            "[orchestrator] Running %s for %s", step_name, incident_id
        )
        result: list[IncidentState | None] = [None]
        error: list[BaseException | None] = [None]

        def target() -> None:
            try:
                result[0] = function()
            except BaseException as caught_error:
                error[0] = caught_error

        thread = threading.Thread(
            target=target,
            name=f"{step_name}-{incident_id}",
            daemon=True,
        )
        thread.start()
        thread.join(timeout=self._agent_timeout_seconds)

        if thread.is_alive():
            raise TimeoutError(
                f"{step_name} timed out after "
                f"{self._agent_timeout_seconds:g}s"
            )
        if error[0]:
            raise error[0]
        if result[0] is None:
            raise RuntimeError(f"{step_name} returned no incident state")

        logger.info(
            "[orchestrator] %s complete for %s", step_name, incident_id
        )
        return result[0]

    def _store_and_emit(self, state: IncidentState) -> None:
        with self._lock:
            self._active[state.incident_id] = state
        self._write_active_snapshot()
        self._emit_callback(self.on_state_update, state, "on_state_update")

    def _finish_incident(
        self, trigger: SentryTrigger, state: IncidentState
    ) -> None:
        try:
            record_incident(state)
        except Exception:
            logger.exception(
                "[orchestrator] Failed to record metrics for %s",
                state.incident_id,
            )

        self.sentry.clear_incident(trigger.incident_type)
        self._emit_callback(self.on_incident_done, state, "on_incident_done")

        with self._lock:
            self._active.pop(trigger.incident_id, None)
            self._known_ids.discard(trigger.incident_id)
            self._known_types.discard(trigger.incident_type)

        logger.info(
            "[orchestrator] Incident %s finished with status=%s mttd=%.2fs",
            state.incident_id,
            state.status,
            state.mttd_seconds or 0.0,
        )
        self._write_active_snapshot()

    # ------------------------------------------------------------------
    # watchdog — force-close stuck incidents
    # ------------------------------------------------------------------

    def _watchdog_loop(self) -> None:
        while self._running.is_set():
            time.sleep(30)
            now = datetime.now()
            with self._lock:
                stuck = [
                    state for state in self._active.values()
                    if state.status == "active"
                    and (now - state.started_at).total_seconds() > STUCK_INCIDENT_THRESHOLD_SECONDS
                ]
            for state in stuck:
                logger.warning(
                    "[orchestrator] Incident %s stuck for >%ds — force closing",
                    state.incident_id, STUCK_INCIDENT_THRESHOLD_SECONDS,
                )
                self._force_close_stuck(state)

    def _force_close_stuck(self, state: IncidentState) -> None:
        state.status = "timeout"
        try:
            record_incident(state)
        except Exception:
            logger.exception(
                "[orchestrator] Failed to record metrics for timed-out %s",
                state.incident_id,
            )
        self.sentry.clear_incident(state.incident_type)
        with self._lock:
            self._active.pop(state.incident_id, None)
            self._known_ids.discard(state.incident_id)
            self._known_types.discard(state.incident_type)
        logger.error("[orchestrator] Incident %s marked as timeout and cleared", state.incident_id)
        self._write_active_snapshot()

    def _emit_callback(
        self,
        callback: Callable[[IncidentState], None] | None,
        state: IncidentState,
        callback_name: str,
    ) -> None:
        if not callback:
            return
        try:
            callback(state)
        except Exception as error:
            logger.warning(
                "[orchestrator] %s callback failed: %s",
                callback_name,
                error,
            )

    # ------------------------------------------------------------------
    # command polling — picks up resolve/cancel commands from dashboards
    # ------------------------------------------------------------------

    def _command_loop(self) -> None:
        while self._running.is_set():
            time.sleep(2)
            try:
                pending = get_pending_commands()
            except Exception as e:
                logger.error("[orchestrator] Failed reading commands: %s", e)
                continue

            for cmd in pending:
                incident_id = cmd["incident_id"]
                action      = cmd["action"]
                reason      = cmd.get("reason", "")

                if action == "resolve":
                    ok = self.manually_resolve(
                        incident_id,
                        reason=reason or "Manually resolved via dashboard",
                    )
                    logger.info(
                        "[orchestrator] Command 'resolve' for %s → %s",
                        incident_id, "OK" if ok else "NOT FOUND",
                    )
                elif action == "cancel":
                    ok = self.manually_resolve(
                        incident_id,
                        reason=reason or "Cancelled via dashboard",
                    )
                    logger.info(
                        "[orchestrator] Command 'cancel' for %s → %s",
                        incident_id, "OK" if ok else "NOT FOUND",
                    )
                else:
                    logger.warning("[orchestrator] Unknown command action: %s", action)

                mark_processed(cmd["submitted_at"])

    # ------------------------------------------------------------------
    # active incident snapshot — written to disk for Streamlit to read
    # ------------------------------------------------------------------

    def _write_active_snapshot(self) -> None:
        import os
        os.makedirs("logs", exist_ok=True)
        with self._lock:
            snapshot = [
                {
                    "incident_id":       s.incident_id,
                    "incident_type":     s.incident_type,
                    "severity":          s.severity,
                    "affected_services": s.affected_services,
                    "started_at":        s.started_at.isoformat(),
                    "status":            s.status,
                    "diagnosis":         (s.diagnosis or "")[:300],
                }
                for s in self._active.values()
            ]
        with open(ACTIVE_SNAPSHOT_FILE, "w") as f:
            json.dump(snapshot, f, indent=2)
