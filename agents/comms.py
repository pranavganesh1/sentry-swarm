import logging
import os
from datetime import datetime

from dotenv import load_dotenv
from langchain_core.output_parsers import PydanticOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI
from pydantic import BaseModel, Field
from tenacity import retry, stop_after_attempt, wait_exponential

from state import IncidentState


load_dotenv()
logger = logging.getLogger("comms")


class SlackUpdate(BaseModel):
    severity_emoji: str = Field(
        description=(
            "Single emoji representing severity: "
            "\\U0001f534 critical, \\U0001f7e0 high, "
            "\\U0001f7e1 medium, \\U0001f7e2 low"
        )
    )
    status: str = Field(
        description="One of: investigating, identified, monitoring, resolved"
    )
    headline: str = Field(
        description="One sentence: what is broken and who is affected"
    )
    impact: str = Field(
        description="User-facing impact in plain English, one sentence"
    )
    current_action: str = Field(
        description="What the team is doing RIGHT NOW, one sentence"
    )
    eta: str = Field(description="Estimated resolution time or 'Under investigation'")
    incident_id: str = Field(description="The incident ID for tracking")


class PostMortem(BaseModel):
    title: str = Field(
        description="Short incident title, e.g. 'DB connection pool exhaustion - 2024-01-01'"
    )
    severity: str
    duration_minutes: int = Field(
        description="How long the incident lasted in minutes"
    )
    summary: str = Field(
        description="2-3 sentence executive summary of what happened"
    )
    timeline: list[str] = Field(
        description=(
            "Ordered list of timestamped events, "
            "e.g. '12:00 - First error detected in db-proxy'"
        )
    )
    root_cause: str = Field(description="Technical root cause in 1-2 sentences")
    impact: str = Field(description="What broke, what users experienced")
    resolution: str = Field(description="What fixed it")
    action_items: list[str] = Field(
        description=(
            "Concrete follow-up tasks to prevent recurrence, each starting with a verb"
        )
    )
    lessons_learned: list[str] = Field(
        description="2-3 honest lessons from this incident"
    )


slack_parser = PydanticOutputParser(pydantic_object=SlackUpdate)
postmortem_parser = PydanticOutputParser(pydantic_object=PostMortem)

SLACK_SYSTEM = """You are an SRE writing a Slack incident update.
Rules:
- Plain English, no jargon the whole company cannot understand
- Status must reflect what is actually happening right now
- Impact must describe the user experience, not the technical cause
- Current action must be specific, not "we are investigating"
- Keep every field concise because Slack is not a post-mortem

{format_instructions}"""

SLACK_USER = """
## Incident
- ID: {incident_id}
- Type: {incident_type}
- Severity: {severity}
- Affected services: {affected_services}
- Started at: {started_at}

## Diagnosis
{diagnosis}

## Fix Plan (first 3 immediate steps)
{fix_steps}

Write the Slack update now.
"""

slack_prompt = ChatPromptTemplate.from_messages(
    [
        ("system", SLACK_SYSTEM),
        ("user", SLACK_USER),
    ]
).partial(format_instructions=slack_parser.get_format_instructions())

POSTMORTEM_SYSTEM = """You are an SRE writing a blameless post-mortem document.
Rules:
- Blameless: focus on systems and processes, never individuals
- Timeline must be specific with real timestamps from the incident data
- Action items must be concrete and assignable, not vague
- Lessons learned must be honest, not PR-speak
- Root cause must be technical and precise

{format_instructions}"""

POSTMORTEM_USER = """
## Incident Data
- ID: {incident_id}
- Type: {incident_type}
- Severity: {severity}
- Affected services: {affected_services}
- Started at: {started_at}
- Detected at: {detected_at}
- MTTD: {mttd_seconds} seconds
- Status: {status}

## Diagnosis
{diagnosis}

## Fix Plan Applied
{fix_steps}

Write the full post-mortem now.
"""

postmortem_prompt = ChatPromptTemplate.from_messages(
    [
        ("system", POSTMORTEM_SYSTEM),
        ("user", POSTMORTEM_USER),
    ]
).partial(format_instructions=postmortem_parser.get_format_instructions())

# Lazy-initialised so missing OPENAI_API_KEY doesn't crash on import
_llm = None
_slack_chain = None
_postmortem_chain = None


def _get_chains():
    global _llm, _slack_chain, _postmortem_chain
    if _llm is None:
        _llm = ChatOpenAI(model="gpt-4o-mini", temperature=0.2)
        _slack_chain = slack_prompt | _llm | slack_parser
        _postmortem_chain = postmortem_prompt | _llm | postmortem_parser
    return _slack_chain, _postmortem_chain


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=8), reraise=True)
def _invoke_slack(payload: dict) -> SlackUpdate:
    slack_chain, _ = _get_chains()
    return slack_chain.invoke(payload)


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=8), reraise=True)
def _invoke_postmortem(payload: dict) -> PostMortem:
    _, postmortem_chain = _get_chains()
    return postmortem_chain.invoke(payload)


class CommsAgent:
    def run(self, state: IncidentState) -> IncidentState:
        logger.info(
            "[comms] Generating comms for incident %s (%s)",
            state.incident_id,
            state.incident_type,
        )

        fix_steps = self._top_fix_steps(state.fix_plan, n=3)
        slack = self._generate_slack(state, fix_steps)
        postmortem = self._generate_postmortem(state, fix_steps)

        state.comms_update = self._format_slack(slack)
        state.post_mortem = self._format_postmortem(postmortem, state)
        state.status = "resolved"
        self._save_postmortem(state)

        logger.info("[comms] Slack update and post-mortem ready")
        self._log_slack(slack)
        return state

    def _generate_slack(self, state: IncidentState, fix_steps: str) -> SlackUpdate:
        payload = {
            "incident_id": state.incident_id,
            "incident_type": state.incident_type,
            "severity": state.severity,
            "affected_services": ", ".join(state.affected_services),
            "started_at": state.started_at.strftime("%H:%M:%S"),
            "diagnosis": state.diagnosis or "Diagnosis not available",
            "fix_steps": fix_steps,
        }
        try:
            return _invoke_slack(payload)
        except Exception as e:
            logger.error("[comms] Slack LLM failed after retries, using fallback: %s", e)
            return self._fallback_slack(state)

    def _generate_postmortem(
        self, state: IncidentState, fix_steps: str
    ) -> PostMortem:
        duration = int((datetime.now() - state.started_at).total_seconds() / 60)
        payload = {
            "incident_id": state.incident_id,
            "incident_type": state.incident_type,
            "severity": state.severity,
            "affected_services": ", ".join(state.affected_services),
            "started_at": state.started_at.strftime("%Y-%m-%d %H:%M:%S"),
            "detected_at": (
                state.detected_at.strftime("%Y-%m-%d %H:%M:%S")
                if state.detected_at
                else "unknown"
            ),
            "mttd_seconds": state.mttd_seconds or 0,
            "status": state.status,
            "diagnosis": state.diagnosis or "Not available",
            "fix_steps": fix_steps,
        }
        try:
            return _invoke_postmortem(payload)
        except Exception as e:
            logger.error("[comms] Postmortem LLM failed after retries, using fallback: %s", e)
            return self._fallback_postmortem(state, duration)

    def _fallback_slack(self, state: IncidentState) -> SlackUpdate:
        severity_map = {"critical": "\U0001f534", "high": "\U0001f7e0",
                        "medium": "\U0001f7e1", "low": "\U0001f7e2"}
        return SlackUpdate(
            severity_emoji=severity_map.get(state.severity, "\U0001f7e1"),
            status="investigating",
            headline=f"{state.incident_type} incident affecting {', '.join(state.affected_services)}",
            impact="User impact is being assessed (AI comms unavailable)",
            current_action="Engineering team is investigating and following runbook procedures",
            eta="Under investigation",
            incident_id=state.incident_id,
        )

    def _fallback_postmortem(self, state: IncidentState, duration: int) -> PostMortem:
        return PostMortem(
            title=f"{state.incident_type} — {state.started_at.strftime('%Y-%m-%d %H:%M')}",
            severity=state.severity,
            duration_minutes=max(1, duration),
            summary=f"Automated post-mortem unavailable due to AI service outage. "
                    f"Incident type: {state.incident_type}. "
                    f"Diagnosis: {state.diagnosis or 'N/A'}",
            timeline=[f"{state.started_at.strftime('%H:%M')} - Incident started",
                      f"{(state.detected_at or state.started_at).strftime('%H:%M')} - Detected by Sentry"],
            root_cause=state.diagnosis or "Root cause analysis pending manual review",
            impact=f"Services affected: {', '.join(state.affected_services)}",
            resolution="See fix plan for applied remediation steps",
            action_items=["Review incident manually and update this post-mortem",
                          "Investigate AI service outage that prevented auto-generation"],
            lessons_learned=["AI-generated comms require fallback paths",
                             "Manual review still needed for AI-degraded incidents"],
        )

    def _top_fix_steps(self, fix_plan: list[str] | None, n: int = 3) -> str:
        if not fix_plan:
            return "No fix plan available"

        immediate = []
        for line in fix_plan:
            if "FOLLOWUP" in line:
                break
            immediate.append(line)

        return "\n".join(immediate[: n * 3])

    def _format_slack(self, slack: SlackUpdate) -> str:
        return "\n".join(
            [
                f"{slack.severity_emoji} *INCIDENT {slack.incident_id}* | {slack.status.upper()}",
                f"*{slack.headline}*",
                "",
                f"*Impact:* {slack.impact}",
                f"*Action:* {slack.current_action}",
                f"*ETA:* {slack.eta}",
                "",
                f"_Incident ID: {slack.incident_id} | Updates every 15 min_",
            ]
        )

    def _format_postmortem(self, postmortem: PostMortem, state: IncidentState) -> str:
        lines = [
            f"# Post-Mortem: {postmortem.title}",
            "",
            f"**Severity:** {postmortem.severity}  ",
            f"**Duration:** {postmortem.duration_minutes} minutes  ",
            f"**MTTD:** {state.mttd_seconds}s  ",
            "**Status:** Resolved  ",
            "",
            "## Summary",
            postmortem.summary,
            "",
            "## Timeline",
        ]

        for event in postmortem.timeline:
            lines.append(f"- {event}")

        lines.extend(
            [
                "",
                "## Root Cause",
                postmortem.root_cause,
                "",
                "## Impact",
                postmortem.impact,
                "",
                "## Resolution",
                postmortem.resolution,
                "",
                "## Action Items",
            ]
        )

        for item in postmortem.action_items:
            lines.append(f"- [ ] {item}")

        lines.extend(["", "## Lessons Learned"])
        for lesson in postmortem.lessons_learned:
            lines.append(f"- {lesson}")

        return "\n".join(lines)

    def _save_postmortem(self, state: IncidentState) -> None:
        os.makedirs("postmortems", exist_ok=True)
        date_str = datetime.now().strftime("%Y-%m-%d_%H-%M")
        filename = (
            f"postmortems/{date_str}_{state.incident_id}_{state.incident_type}.md"
        )
        with open(filename, "w", encoding="utf-8") as postmortem_file:
            postmortem_file.write(state.post_mortem or "")
        logger.info("[comms] Post-mortem saved to %s", filename)

    def _log_slack(self, slack: SlackUpdate) -> None:
        logger.info("[comms] ---------------------------------")
        logger.info("[comms] Slack update:")
        logger.info(
            "[comms]   %s INCIDENT %s | %s",
            slack.severity_emoji,
            slack.incident_id,
            slack.status.upper(),
        )
        logger.info("[comms]   %s", slack.headline)
        logger.info("[comms]   Impact: %s", slack.impact)
        logger.info("[comms]   Action: %s", slack.current_action)
        logger.info("[comms]   ETA: %s", slack.eta)
        logger.info("[comms] ---------------------------------")
