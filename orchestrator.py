from __future__ import annotations

import logging
import queue
import threading
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from metrics import get_summary, record_incident
from state import IncidentState

if TYPE_CHECKING:
    from agents.sentry import SentryTrigger


logger = logging.getLogger("orchestrator")

MAX_CONCURRENT_INCIDENTS = 3
AGENT_TIMEOUT_SECONDS = 120


class IncidentOrchestrator:
    def __init__(
        self,
        *,
        sentry: Any | None = None,
        diagnostician: Any | None = None,
        fix_planner: Any | None = None,
        comms: Any | None = None,
        agent_timeout_seconds: float = AGENT_TIMEOUT_SECONDS,
    ):
        self._queue: queue.Queue[SentryTrigger | None] = queue.Queue()
        self._active: dict[str, IncidentState] = {}
        self._known_ids: set[str] = set()
        self._known_types: set[str] = set()
        self._lock = threading.RLock()
        self._running = threading.Event()
        self._workers: list[threading.Thread] = []
        self._sentry_thread: threading.Thread | None = None
        self._agent_timeout_seconds = agent_timeout_seconds

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

        logger.info(
            "[orchestrator] Running with %d incident workers",
            MAX_CONCURRENT_INCIDENTS,
        )

    def stop(self, join_timeout: float = 5.0) -> None:
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

    def get_metrics(self) -> dict:
        return get_summary()

    def inject_incident(self, trigger: SentryTrigger) -> bool:
        logger.info(
            "[orchestrator] Manual inject: %s", trigger.incident_type
        )
        return self._enqueue(trigger)

    def _enqueue(self, trigger: SentryTrigger) -> bool:
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
        state = self._initial_state(trigger)
        self._store_and_emit(state)
        logger.info(
            "[orchestrator] Pipeline started for %s (%s)",
            incident_id,
            trigger.incident_type,
        )

        try:
            state = self._run_step(
                "diagnostician",
                incident_id,
                lambda: self.diagnostician.run(trigger),
            )
            self._store_and_emit(state)

            state = self._run_step(
                "fix_planner",
                incident_id,
                lambda: self.fix_planner.run(state),
            )
            self._store_and_emit(state)

            state = self._run_step(
                "comms",
                incident_id,
                lambda: self.comms.run(state),
            )
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
