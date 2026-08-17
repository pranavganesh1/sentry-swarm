from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

from state import IncidentState

if TYPE_CHECKING:
    from agents.sentry import SentryTrigger


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
    """Agent responsible for diagnosing incidents based on trigger events.

    Uses runbook information and trigger evidence to generate diagnostic
    information for incidents, with fallback capabilities when external
    services are unavailable.
    """

    def run(self, trigger: SentryTrigger) -> IncidentState:
        """Process a trigger event to generate incident diagnosis.

        Args:
            trigger: The triggering event containing incident information

        Returns:
            IncidentState: Updated incident state with diagnosis information
        """
        logger.info(
            "[diagnostician] Diagnosing incident %s (%s)",
            trigger.incident_id,
            trigger.incident_type,
        )

        mttd_seconds = max(
            0.0, (trigger.detected_at - trigger.started_at).total_seconds()
        )

        try:
            diagnosis_text = self._build_diagnosis(trigger)
        except Exception as e:
            logger.error("[diagnostician] Failed, using fallback: %s", e)
            diagnosis_text = self._fallback_diagnosis(trigger)

        state = IncidentState(
            incident_id=trigger.incident_id,
            incident_type=trigger.incident_type,
            severity=trigger.severity,
            affected_services=list(trigger.affected_services),
            trigger_events=list(trigger.trigger_events),
            started_at=trigger.started_at,
            detected_at=trigger.detected_at,
            mttd_seconds=round(mttd_seconds, 2),
            diagnosis=diagnosis_text,
            status="diagnosed",
        )

        logger.info(
            "[diagnostician] Diagnosis complete for %s (mttd=%.2fs)",
            trigger.incident_id,
            state.mttd_seconds,
        )
        return state

    def _build_diagnosis(self, trigger: SentryTrigger) -> str:
        """Build diagnosis by combining trigger data with runbook information.

        Args:
            trigger: The triggering event containing incident information

        Returns:
            str: Formatted diagnosis string combining incident pattern,
                 affected services, trigger evidence, runbook info, and confidence
        """
        runbook_path = self._find_runbook(trigger.incident_type)
        evidence = self._summarize_evidence(trigger.trigger_events)
        services = ", ".join(trigger.affected_services) or "unknown services"
        return "\n".join(
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

    def _fallback_diagnosis(self, trigger: SentryTrigger) -> str:
        """Fallback when normal diagnosis fails — keeps the pipeline alive with
        best-effort info derived directly from the trigger, no LLM needed."""
        messages = [str(e.get("message", "")).strip()
                    for e in trigger.trigger_events[:5] if e.get("message")]
        error_chain = " | ".join(messages) if messages else "No trigger messages"
        return "\n".join([
            f"[FALLBACK DIAGNOSIS — normal path failed]",
            f"Incident pattern: {trigger.summary}",
            f"Affected services: {', '.join(trigger.affected_services) or 'unknown'}",
            f"Error chain: {error_chain}",
            f"Relevant runbook: {trigger.incident_type}.md",
            f"Confidence: 0.30 (fallback — needs escalation)",
        ])

    def _find_runbook(self, incident_type: str) -> Path | None:
        """Locate the runbook for an incident type via RAG or direct file lookup.

        Tries the RAG retriever first; falls back to a static file mapping
        in RUNBOOK_FILES if the retriever is unavailable.

        Args:
            incident_type: The classified incident type string.

        Returns:
            Path to the matching runbook file, or None if not found.
        """
        try:
            from ingestion.retriever import retrieve_relevant_runbook
            rb = retrieve_relevant_runbook(incident_type, incident_type)
            if rb and rb.get("path"):
                return Path(rb["path"])
        except Exception as e:
            logger.warning("[diagnostician] RAG retrieval failed, using direct resolution: %s", e)

        filename = RUNBOOK_FILES.get(incident_type)
        if not filename:
            return None

        path = RUNBOOK_DIRECTORY / filename
        return path if path.exists() else None

    def _summarize_evidence(self, events: list[dict], limit: int = 3) -> str:
        """Extract and join the first *limit* trigger event messages.

        Args:
            events: Raw trigger event dicts, each optionally containing a
                ``message`` key.
            limit: Maximum number of messages to include.

        Returns:
            A pipe-delimited summary string, or a fallback message if no
            trigger messages were captured.
        """
        messages = [
            str(event.get("message", "")).strip()
            for event in events
            if event.get("message")
        ]
        if not messages:
            return "No trigger messages were captured"
        return " | ".join(messages[:limit])
