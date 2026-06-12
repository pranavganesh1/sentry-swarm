import logging
from datetime import datetime, timedelta

from agents.comms import CommsAgent
from state import IncidentState


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(message)s",
    datefmt="%H:%M:%S",
)

now = datetime.now()

state = IncidentState(
    incident_id="test-003",
    incident_type="db_timeout",
    severity="high",
    affected_services=["db-proxy", "user-api", "auth-service"],
    trigger_events=[],
    started_at=now - timedelta(minutes=12),
    detected_at=now - timedelta(minutes=11, seconds=35),
    mttd_seconds=25.0,
    status="active",
    diagnosis="\n".join(
        [
            "Root cause: DB proxy exhausted connection pool blocking all upstream queries",
            "Error chain: db-proxy timeout -> pool exhausted -> user-api failure -> auth-service failure",
            "Relevant runbook: db_timeout.md",
            "Key sections: Triage Steps, Kill long-running queries, Restart db-proxy",
            "Needs escalation: False",
            "Confidence: 0.96",
        ]
    ),
    fix_plan=[
        "=== IMMEDIATE STEPS ===",
        "1. Kill long-running queries",
        "   $ psql -c \"SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE now() - query_start > interval '30 seconds' AND state = 'active';\"",
        "   -> Long-running queries terminated, freeing pool connections",
        "2. Restart db-proxy",
        "   $ kubectl rollout restart deployment/db-proxy",
        "   -> db-proxy restarts with fresh connection pool",
        "3. Verify pool recovery",
        "   $ kubectl logs deployment/db-proxy --tail=50",
        "   -> No more pool exhausted warnings in logs",
        "",
        "=== FOLLOWUP STEPS ===",
        "1. Add slow query alert",
        "   $ kubectl apply -f alerts/db-slow-query.yaml",
        "   -> Alert fires when any query exceeds 10s",
    ],
)

agent = CommsAgent()
state = agent.run(state)

print(f"\n{'=' * 60}")
print("SLACK UPDATE")
print(f"{'=' * 60}")
print(state.comms_update)

print(f"\n{'=' * 60}")
print("POST-MORTEM")
print(f"{'=' * 60}")
print(state.post_mortem)
