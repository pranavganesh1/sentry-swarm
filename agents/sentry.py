import time
import uuid
import logging
from datetime import datetime
from dataclasses import dataclass
from typing import Callable, List, Dict, Any

from ingestion.buffer import get_error_rate, get_error_events, get_recent_events_mixed
from agents.classifier import classify_events, ClassifierOutput

logger = logging.getLogger("sentry")

# --- tuneable thresholds ---
ERROR_RATE_THRESHOLD = 8.0       # % errors in last 30s to trigger classifier
MIN_ERROR_COUNT      = 3         # at least this many errors before classifying
POLL_INTERVAL        = 5         # seconds between buffer checks
COOLDOWN_SECONDS     = 45        # seconds before same incident type can fire again
LOOKBACK_SECONDS     = 30        # window for error rate calculation

@dataclass
class SentryTrigger:
    incident_id: str
    incident_type: str
    severity: str
    affected_services: list[str]
    confidence: float
    summary: str
    trigger_events: list[dict]
    started_at: datetime
    detected_at: datetime

class SentryAgent:
    def __init__(self, on_incident: Callable[[SentryTrigger], None]):
        """
        on_incident: callback fired when a real incident is detected.
        Receives a SentryTrigger — pass it to the orchestrator.
        """
        self.on_incident   = on_incident
        self._running      = False
        self._cooldowns: dict[str, float] = {}   # incident_type → last fired timestamp
        self._active_types: set[str] = set()     # currently open incident types
        self._active_severities: dict[str, str] = {}  # incident_type → severity

    # ------------------------------------------------------------------
    # public API
    # ------------------------------------------------------------------

    def start(self):
        """Blocking loop — run in a thread."""
        self._running = True
        logger.info("[sentry] Started. Polling every %ds, threshold=%.1f%%",
                    POLL_INTERVAL, ERROR_RATE_THRESHOLD)
        while self._running:
            try:
                self._tick()
            except Exception as e:
                logger.error("[sentry] Tick error: %s", e)
            time.sleep(POLL_INTERVAL)

    def stop(self):
        self._running = False

    def clear_incident(self, incident_type: str):
        """Called by orchestrator when incident resolves."""
        self._active_types.discard(incident_type)
        logger.info("[sentry] Cleared active incident: %s", incident_type)

    # ------------------------------------------------------------------
    # internal
    # ------------------------------------------------------------------

    def _tick(self):
        error_rate = get_error_rate(since_seconds=LOOKBACK_SECONDS)
        error_events = get_error_events(since_seconds=LOOKBACK_SECONDS)

        logger.debug("[sentry] error_rate=%.1f%% error_count=%d",
                     error_rate, len(error_events))

        # gate 1 — error rate too low
        if error_rate < ERROR_RATE_THRESHOLD:
            return

        # gate 2 — not enough errors to be meaningful
        if len(error_events) < MIN_ERROR_COUNT:
            return

        # classify
        mixed_events = get_recent_events_mixed(since_seconds=LOOKBACK_SECONDS)
        result: ClassifierOutput = classify_events(mixed_events)

        # gate 3 — LLM says no incident
        if not result.is_incident:
            logger.debug("[sentry] Classifier says no incident (type=%s)", result.incident_type)
            return

        # gate 4 — already active, unless severity escalated
        if result.incident_type in self._active_types:
            prev_severity = self._active_severities.get(result.incident_type, "low")
            severity_rank = {"low": 1, "medium": 2, "high": 3, "critical": 4}
            if severity_rank.get(result.severity, 0) <= severity_rank.get(prev_severity, 0):
                logger.debug("[sentry] Incident type %s already active at same/lower severity, skipping",
                             result.incident_type)
                return
            else:
                logger.warning(
                    "[sentry] Incident type %s ESCALATED %s → %s — re-firing",
                    result.incident_type, prev_severity, result.severity,
                )

        # gate 5 — cooldown
        if self._in_cooldown(result.incident_type):
            logger.debug("[sentry] Incident type %s in cooldown", result.incident_type)
            return

        # fire
        self._fire(result, error_events)

    def _in_cooldown(self, incident_type: str) -> bool:
        last = self._cooldowns.get(incident_type, 0)
        return (time.time() - last) < COOLDOWN_SECONDS

    def _fire(self, result: ClassifierOutput, trigger_events: list[dict]):
        now = datetime.now()

        # estimate when spike started — timestamp of first error event in batch
        started_at = now
        if trigger_events:
            try:
                started_at = datetime.fromisoformat(trigger_events[0]["timestamp"])
            except Exception:
                pass

        trigger = SentryTrigger(
            incident_id      = str(uuid.uuid4())[:8],
            incident_type    = result.incident_type,
            severity         = result.severity,
            affected_services= result.affected_services,
            confidence       = result.confidence,
            summary          = result.summary,
            trigger_events   = trigger_events,
            started_at       = started_at,
            detected_at      = now,
        )

        self._active_types.add(result.incident_type)
        self._active_severities[result.incident_type] = result.severity
        self._cooldowns[result.incident_type] = time.time()

        logger.info(
            "[sentry] INCIDENT DETECTED | id=%s type=%s severity=%s confidence=%.2f",
            trigger.incident_id, trigger.incident_type,
            trigger.severity, trigger.confidence,
        )
        logger.info("[sentry]    summary: %s", trigger.summary)

        self.on_incident(trigger)
    def handle_physical_event(self, raw_payload: str) -> None:
        """Entry point for UNO Q sensor data.
        The raw payload is expected to be a JSON string; we delegate
        parsing to sensors.ingest_payload which returns a PhysicalTrigger,
        then convert it to SentryTrigger format for processing.
        """
        from sensors import ingest_payload
        physical_trigger = ingest_payload(raw_payload)

        # Convert PhysicalTrigger to SentryTrigger-compatible format
        # Map physical trigger events to the expected dict format
        trigger_events = []
        if physical_trigger.trigger_events:
            # PhysicalTrigger has trigger_events as list[str], convert to list[dict]
            for i, event_str in enumerate(physical_trigger.trigger_events):
                trigger_events.append({
                    "timestamp": physical_trigger.detected_at.isoformat(),
                    "level": "INFO",  # Default level for physical events
                    "service": physical_trigger.source,
                    "message": str(event_str),
                    "incident_type": physical_trigger.incident_type,
                    "raw": str(event_str)
                })

        # Create SentryTrigger with compatible fields
        sentry_trigger = SentryTrigger(
            incident_id=physical_trigger.incident_id,
            incident_type=physical_trigger.incident_type,
            severity=physical_trigger.severity,
            affected_services=physical_trigger.affected_services or [],
            confidence=physical_trigger.confidence,
            summary=physical_trigger.summary,
            trigger_events=trigger_events,
            started_at=physical_trigger.started_at,
            detected_at=physical_trigger.detected_at
        )

        self.on_incident(sentry_trigger)
