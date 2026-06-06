from agents.classifier import classify_events
from ingestion.buffer import get_error_events


NORMAL_EVENTS = [
    {
        "timestamp": "2024-01-01 12:00:01",
        "level": "INFO",
        "service": "auth-service",
        "message": "GET /api/login 200 45ms",
        "incident_type": None,
    },
    {
        "timestamp": "2024-01-01 12:00:02",
        "level": "DEBUG",
        "service": "user-api",
        "message": "DB query completed in 23ms",
        "incident_type": None,
    },
    {
        "timestamp": "2024-01-01 12:00:03",
        "level": "INFO",
        "service": "payment-service",
        "message": "POST /api/pay 201 88ms",
        "incident_type": None,
    },
    {
        "timestamp": "2024-01-01 12:00:04",
        "level": "INFO",
        "service": "nginx",
        "message": "GET /api/products 200 31ms",
        "incident_type": None,
    },
]

DB_EVENTS = [
    {
        "timestamp": "2024-01-01 12:01:00",
        "level": "ERROR",
        "service": "db-proxy",
        "message": "Connection timeout after 30000ms",
        "incident_type": "db_timeout",
    },
    {
        "timestamp": "2024-01-01 12:01:01",
        "level": "ERROR",
        "service": "db-proxy",
        "message": "Query exceeded max execution time",
        "incident_type": "db_timeout",
    },
    {
        "timestamp": "2024-01-01 12:01:02",
        "level": "WARN",
        "service": "db-proxy",
        "message": "Connection pool exhausted (50/50 connections used)",
        "incident_type": "db_timeout",
    },
    {
        "timestamp": "2024-01-01 12:01:03",
        "level": "ERROR",
        "service": "user-api",
        "message": "Failed to fetch user data: upstream db-proxy timeout",
        "incident_type": "db_timeout",
    },
    {
        "timestamp": "2024-01-01 12:01:04",
        "level": "ERROR",
        "service": "auth-service",
        "message": "Failed to validate session: upstream db-proxy timeout",
        "incident_type": "db_timeout",
    },
]

OOM_EVENTS = [
    {
        "timestamp": "2024-01-01 12:02:00",
        "level": "WARN",
        "service": "payment-service",
        "message": "Memory usage at 91% - approaching limit",
        "incident_type": "oom_kill",
    },
    {
        "timestamp": "2024-01-01 12:02:01",
        "level": "FATAL",
        "service": "payment-service",
        "message": "OutOfMemoryError: Java heap space",
        "incident_type": "oom_kill",
    },
    {
        "timestamp": "2024-01-01 12:02:02",
        "level": "ERROR",
        "service": "payment-service",
        "message": "Process killed by OOM killer (RSS: 1024MB)",
        "incident_type": "oom_kill",
    },
    {
        "timestamp": "2024-01-01 12:02:03",
        "level": "ERROR",
        "service": "nginx",
        "message": "upstream payment-service unavailable (connection refused)",
        "incident_type": "oom_kill",
    },
]


def print_result(name: str, events: list[dict]) -> None:
    print(f"\n{'=' * 60}")
    print(f"TEST: {name}")
    print(f"{'=' * 60}")
    result = classify_events(events)
    print(f"  is_incident   : {result.is_incident}")
    print(f"  incident_type : {result.incident_type}")
    print(f"  severity      : {result.severity}")
    print(f"  services      : {result.affected_services}")
    print(f"  confidence    : {result.confidence}")
    print(f"  summary       : {result.summary}")


def main() -> None:
    tests = [
        ("Normal traffic", NORMAL_EVENTS),
        ("DB timeout spike", DB_EVENTS),
        ("OOM kill", OOM_EVENTS),
    ]

    for name, events in tests:
        print_result(name, events)

    print(f"\n{'=' * 60}")
    print("TEST: Live buffer (last 30s of error events)")
    print(f"{'=' * 60}")

    live_events = get_error_events(since_seconds=30)
    if live_events:
        result = classify_events(live_events)
        print(f"  is_incident   : {result.is_incident}")
        print(f"  incident_type : {result.incident_type}")
        print(f"  severity      : {result.severity}")
        print(f"  summary       : {result.summary}")
    else:
        print("  No error events in the last 30 seconds - run log_generator.py first")


if __name__ == "__main__":
    main()
