import logging
from pathlib import Path

from agents.diagnostician import RUNBOOK_DIRECTORY, RUNBOOK_FILES
from state import IncidentState


logger = logging.getLogger("fix_planner")


class FixPlannerAgent:
    def run(self, state: IncidentState) -> IncidentState:
        logger.info(
            "[fix_planner] Building plan for incident %s (%s)",
            state.incident_id,
            state.incident_type,
        )

        runbook_path = self._runbook_path(state.incident_type)
        remediation_steps = self._extract_section(
            runbook_path, "## Remediation Steps", "## Escalation"
        )
        escalation_steps = self._extract_section(
            runbook_path, "## Escalation", "## Post-Mortem Tags"
        )

        plan = ["=== IMMEDIATE STEPS ==="]
        if remediation_steps:
            plan.extend(remediation_steps)
        else:
            plan.append(
                "1. Stabilize affected services and inspect recent logs."
            )

        plan.extend(["", "=== FOLLOWUP STEPS ==="])
        if escalation_steps:
            plan.extend(escalation_steps)
        plan.extend(
            [
                "1. Verify error rates and service health return to baseline.",
                "2. Capture findings and assign preventive action items.",
            ]
        )

        state.fix_plan = plan
        state.status = "fix_planned"
        logger.info("[fix_planner] Plan ready for %s", state.incident_id)
        return state

    def _runbook_path(self, incident_type: str) -> Path | None:
        try:
            from ingestion.retriever import retrieve_relevant_runbook
            rb = retrieve_relevant_runbook(incident_type, incident_type)
            if rb and rb.get("path"):
                return Path(rb["path"])
        except Exception as e:
            logger.warning("[fix_planner] RAG retrieval failed, using direct resolution: %s", e)

        filename = RUNBOOK_FILES.get(incident_type)
        if not filename:
            return None

        path = RUNBOOK_DIRECTORY / filename
        return path if path.exists() else None

    def _extract_section(
        self, path: Path | None, start_heading: str, end_heading: str
    ) -> list[str]:
        if not path:
            return []

        lines = path.read_text(encoding="utf-8").splitlines()
        try:
            start = lines.index(start_heading) + 1
        except ValueError:
            return []

        try:
            end = lines.index(end_heading, start)
        except ValueError:
            end = len(lines)

        return self._clean_lines(lines[start:end])

    def _clean_lines(self, lines: list[str]) -> list[str]:
        cleaned: list[str] = []
        in_code_block = False
        for line in lines:
            stripped = line.strip()
            if stripped.startswith("```"):
                in_code_block = not in_code_block
                continue
            if not stripped:
                continue
            if in_code_block:
                cleaned.append(f"   $ {stripped}")
            elif stripped.startswith("### "):
                cleaned.append(stripped.removeprefix("### "))
            else:
                cleaned.append(stripped)
        return cleaned
