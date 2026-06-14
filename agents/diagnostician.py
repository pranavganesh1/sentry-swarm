import logging
from pathlib import Path

from agents.sentry import SentryTrigger
from state import IncidentState


logger = logging.getLogger("diagnostician")
RUNBOOK_DIRECTORY = Path("runbooks")
RUNBOOK_FILES = {
    "http_5xx": "http_5xx_spike.md",
    "db_timeout": "db_timeout.md",
    "oom_kill": "oom_kill.md",
    "failed_deploy": "failed_deploy.md",
    "cascading_failure": "cascading_failure.md",
}


class DiagnosticianAgent:
    def run(self, trigger: SentryTrigger) -> IncidentState:
        logger.info(
            "[diagnostician] Diagnosing incident %s (%s)",
            trigger.incident_id,
            trigger.incident_type,
        )

        mttd_seconds = max(
            0.0, (trigger.detected_at - trigger.started_at).total_seconds()
        )
        state = IncidentState(
            incident_id=trigger.incident_id,
            incident_type=trigger.incident_type,
            severity=trigger.severity,
            affected_services=list(trigger.affected_services),
            trigger_events=list(trigger.trigger_events),
            started_at=trigger.started_at,
            detected_at=trigger.detected_at,
            mttd_seconds=round(mttd_seconds, 2),
            status="diagnosed",
        )

        runbook_path = self._find_runbook(trigger.incident_type)
        evidence = self._summarize_evidence(trigger.trigger_events)
        services = ", ".join(trigger.affected_services) or "unknown services"
        state.diagnosis = "\n".join(
            [
                f"Incident pattern: {trigger.summary}",
                f"Affected services: {services}",
                f"Trigger evidence: {evidence}",
                (
                    f"Relevant runbook: {runbook_path.name}"
                    if runbook_path
                    else "Relevant runbook: none found"
                ),
                f"Classifier confidence: {trigger.confidence:.2f}",
            ]
        )

        logger.info(
            "[diagnostician] Diagnosis complete for %s (mttd=%.2fs)",
            trigger.incident_id,
            state.mttd_seconds,
        )
        return state

    def _find_runbook(self, incident_type: str) -> Path | None:
        filename = RUNBOOK_FILES.get(incident_type)
        if not filename:
            return None

        path = RUNBOOK_DIRECTORY / filename
        return path if path.exists() else None

    def _summarize_evidence(self, events: list[dict], limit: int = 3) -> str:
        messages = [
            str(event.get("message", "")).strip()
            for event in events
            if event.get("message")
        ]
        if not messages:
            return "No trigger messages were captured"
        return " | ".join(messages[:limit])
