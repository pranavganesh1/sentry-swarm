from dotenv import load_dotenv
from langchain_core.output_parsers import PydanticOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI
from pydantic import BaseModel, Field


load_dotenv()


class ClassifierOutput(BaseModel):
    incident_type: str = Field(
        description=(
            "One of: http_5xx, db_timeout, oom_kill, failed_deploy, "
            "cascading_failure, none"
        )
    )
    severity: str = Field(description="One of: low, medium, high, critical")
    affected_services: list[str] = Field(
        description="List of service names that appear to be affected"
    )
    confidence: float = Field(description="Confidence score between 0.0 and 1.0")
    summary: str = Field(description="One sentence describing what is happening")
    is_incident: bool = Field(
        description=(
            "True if this batch represents a real incident, False if it is normal noise"
        )
    )


parser = PydanticOutputParser(pydantic_object=ClassifierOutput)

SYSTEM_PROMPT = """You are an expert SRE (Site Reliability Engineer) analyzing production logs.
Your job is to look at a batch of recent log events and determine if an incident is occurring.

Incident types you must detect:
- http_5xx: Spike in 500/503 HTTP errors or unhandled exceptions
- db_timeout: Database connection timeouts or pool exhaustion
- oom_kill: Out of memory errors, process killed by OOM killer
- failed_deploy: Failed deployments, CrashLoopBackOff, pods not starting
- cascading_failure: Multiple services failing simultaneously due to a shared dependency
- none: No incident, normal traffic

Severity rules:
- low: Single isolated error, not recurring
- medium: Repeated errors from one service, not affecting users yet
- high: Multiple services affected or user-facing errors ongoing
- critical: Core infrastructure down, cascading failure, or data loss risk

Be conservative - only set is_incident=True if you see a clear pattern of errors,
not a single one-off error line.

{format_instructions}"""

USER_PROMPT = """Analyze these recent log events and classify any incident:

{log_batch}

Classify this log batch now."""

prompt = ChatPromptTemplate.from_messages(
    [
        ("system", SYSTEM_PROMPT),
        ("user", USER_PROMPT),
    ]
).partial(format_instructions=parser.get_format_instructions())

# Lazy-initialised so missing OPENAI_API_KEY doesn't crash on import
_classifier_chain = None


def _get_chain():
    global _classifier_chain
    if _classifier_chain is None:
        llm = ChatOpenAI(model="gpt-4o-mini", temperature=0)
        _classifier_chain = prompt | llm | parser
    return _classifier_chain


def format_log_batch(events: list[dict]) -> str:
    lines = []
    for event in events:
        incident_type = event.get("incident_type")
        tag = f" [INCIDENT_TYPE:{incident_type}]" if incident_type else ""
        lines.append(
            "[{timestamp}] {level:<5} [{service}] {message}{tag}".format(
                timestamp=event.get("timestamp", "unknown-time"),
                level=event.get("level", "INFO"),
                service=event.get("service", "unknown-service"),
                message=event.get("message", ""),
                tag=tag,
            )
        )
    return "\n".join(lines)


def classify_events(events: list[dict]) -> ClassifierOutput:
    if not events:
        return ClassifierOutput(
            incident_type="none",
            severity="low",
            affected_services=[],
            confidence=1.0,
            summary="No events to analyze.",
            is_incident=False,
        )

    log_batch = format_log_batch(events)
    return _get_chain().invoke({"log_batch": log_batch})
