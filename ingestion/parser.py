import re
from dataclasses import dataclass
from datetime import datetime
from typing import Optional


LEVEL_KEYWORDS = ("DEBUG", "INFO", "WARN", "ERROR", "FATAL")

SPIKE_PATTERNS = {
    "http_5xx": (
        r"500 Internal Server Error",
        r"503 Service Unavailable",
        r"Unhandled exception",
    ),
    "db_timeout": (
        r"Connection timeout",
        r"Query exceeded max execution time",
        r"Connection pool exhausted",
        r"upstream db-proxy timeout",
    ),
    "oom_kill": (
        r"OutOfMemoryError",
        r"OOM killer",
        r"Memory usage at \d+%",
        r"upstream .+ unavailable \(connection refused\)",
    ),
    "failed_deploy": (
        r"Deploy pipeline failed",
        r"CrashLoopBackOff",
        r"ImagePullBackOff",
        r"Health check returned 503 after deploy",
        r"0 ready replicas",
    ),
    "cascading_failure": (
        r"Circuit breaker OPEN",
        r"Connection refused.*upstream",
        r"dependency .+ down",
        r"Failed to authenticate request.*upstream timeout",
    ),
}

LOG_LINE_PATTERN = re.compile(
    r"\[(?P<timestamp>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\]\s+"
    r"(?P<level>DEBUG|INFO|WARN|ERROR|FATAL)\s+"
    r"\[(?P<service>[^\]]+)\]\s+"
    r"(?P<message>.+)"
)


@dataclass(frozen=True)
class LogEvent:
    timestamp: datetime
    level: str
    service: str
    message: str
    incident_type: Optional[str]
    raw: str


def parse_line(line: str) -> Optional[LogEvent]:
    line = line.strip()
    if not line:
        return None

    match = LOG_LINE_PATTERN.match(line)
    if not match:
        return None

    timestamp = datetime.strptime(match.group("timestamp"), "%Y-%m-%d %H:%M:%S")
    message = match.group("message")

    return LogEvent(
        timestamp=timestamp,
        level=match.group("level"),
        service=match.group("service"),
        message=message,
        incident_type=detect_incident_type(message),
        raw=line,
    )


def detect_incident_type(message: str) -> Optional[str]:
    for incident_type, patterns in SPIKE_PATTERNS.items():
        for pattern in patterns:
            if re.search(pattern, message, re.IGNORECASE):
                return incident_type
    return None
