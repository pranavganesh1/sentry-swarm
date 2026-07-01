import logging
import os
from pathlib import Path
from dotenv import load_dotenv

from langchain_core.output_parsers import PydanticOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_google_genai import ChatGoogleGenerativeAI
from pydantic import BaseModel, Field
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from agents.diagnostician import RUNBOOK_DIRECTORY, RUNBOOK_FILES
from state import IncidentState

load_dotenv()
logger = logging.getLogger("fix_planner")

class GeneratedFixPlan(BaseModel):
    immediate_steps: list[str] = Field(
        description="Actionable shell commands or immediate mitigation tasks, each prefixed with a number or '$' command (e.g. '$ kubectl rollout restart deployment/auth')"
    )
    followup_steps: list[str] = Field(
        description="Actions to verify recovery, check logs, and escalate if needed, each starting with a number"
    )
    safety_guidelines: list[str] = Field(
        description="Safety precautions or risk alerts associated with the remediation commands"
    )

parser = PydanticOutputParser(pydantic_object=GeneratedFixPlan)

FIX_PLANNER_SYSTEM = """You are an expert SRE. Your job is to output a structured remediation fix plan for a production incident based on:
1. The incident diagnosis.
2. The relevant runbook text.
3. The specific trigger error logs.

Generate:
- Immediate Steps: concrete action items, shell commands, SQL queries, or deployment actions to stabilize the service.
- Follow-up Steps: post-resolution verification, scaling checks, or escalation criteria.
- Safety Guidelines: risks or precautions to consider (e.g., performance load, data integrity risk).

{format_instructions}"""

FIX_PLANNER_USER = """Generate a customized fix plan for the following incident:

## Incident Metadata
- ID: {incident_id}
- Type: {incident_type}
- Affected Services: {affected_services}

## Incident Diagnosis
{diagnosis}

## Relevant Runbook
{runbook_content}

## Trigger Event Logs
{trigger_logs}

Analyze the logs, diagnosis, and runbook. Generate the structured fix plan now."""

prompt = ChatPromptTemplate.from_messages(
    [
        ("system", FIX_PLANNER_SYSTEM),
        ("user", FIX_PLANNER_USER),
    ]
).partial(format_instructions=parser.get_format_instructions())

_llm = None
_planner_chain = None

def _get_chain():
    global _llm, _planner_chain
    if _llm is None:
        _llm = ChatGoogleGenerativeAI(model="gemini-2.0-flash", temperature=0.2)
        _planner_chain = prompt | _llm | parser
    return _planner_chain

@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=8),
    retry=retry_if_exception_type(Exception),
    reraise=True,
)
def _invoke_planner(payload: dict) -> GeneratedFixPlan:
    return _get_chain().invoke(payload)


class FixPlannerAgent:
    def run(self, state: IncidentState) -> IncidentState:
        logger.info(
            "[fix_planner] Building plan for incident %s (%s)",
            state.incident_id,
            state.incident_type,
        )

        runbook_path = self._runbook_path(state.incident_type)
        runbook_content = ""
        if runbook_path and runbook_path.exists():
            try:
                runbook_content = runbook_path.read_text(encoding="utf-8")
            except Exception as e:
                logger.warning("[fix_planner] Could not read runbook file: %s", e)

        # Check if LLM API is available and key is configured
        if os.getenv("GOOGLE_API_KEY"):
            try:
                # Format trigger event logs
                trigger_logs = ""
                if state.trigger_events:
                    log_lines = []
                    for idx, e in enumerate(state.trigger_events[:10]):
                        log_lines.append(f"[{e.get('timestamp', 'N/A')}] [{e.get('service', 'N/A')}] {e.get('message', 'N/A')}")
                    trigger_logs = "\n".join(log_lines)

                payload = {
                    "incident_id": state.incident_id,
                    "incident_type": state.incident_type,
                    "affected_services": ", ".join(state.affected_services),
                    "diagnosis": state.diagnosis or "No diagnosis details provided.",
                    "runbook_content": runbook_content or "No runbook available.",
                    "trigger_logs": trigger_logs or "No logs available."
                }

                logger.info("[fix_planner] Invoking Gemini LLM for fix plan generation")
                generated = _invoke_planner(payload)

                plan = ["=== IMMEDIATE STEPS ==="]
                plan.extend(generated.immediate_steps)
                plan.extend(["", "=== FOLLOWUP STEPS ==="])
                plan.extend(generated.followup_steps)
                if generated.safety_guidelines:
                    plan.extend(["", "=== SAFETY & RISK GUIDELINES ==="])
                    plan.extend(generated.safety_guidelines)

                state.fix_plan = plan
                state.status = "fix_planned"
                logger.info("[fix_planner] Plan generated successfully via LLM for %s", state.incident_id)
                return state

            except Exception as e:
                logger.warning("[fix_planner] LLM generation failed, falling back to local runbook parsing: %s", e)

        # Fallback to local markdown parsing (rule-based)
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
        logger.info("[fix_planner] Plan ready (fallback parsing) for %s", state.incident_id)
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
