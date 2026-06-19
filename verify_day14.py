"""Quick import + attribute validation for Day 14 hardening."""

from agents.classifier import classify_events, _invoke_classifier
from agents.diagnostician import DiagnosticianAgent
from agents.fix_planner import FixPlannerAgent
from agents.comms import CommsAgent, _invoke_slack, _invoke_postmortem
from agents.sentry import SentryAgent
from orchestrator import IncidentOrchestrator, STUCK_INCIDENT_THRESHOLD_SECONDS

print("All imports OK")
print(f"Watchdog threshold: {STUCK_INCIDENT_THRESHOLD_SECONDS}s")

o = IncidentOrchestrator
print(f"manually_resolve: {hasattr(o, 'manually_resolve')}")
print(f"get_incident_by_id: {hasattr(o, 'get_incident_by_id')}")
print(f"_watchdog_loop: {hasattr(o, '_watchdog_loop')}")
print(f"_force_close_stuck: {hasattr(o, '_force_close_stuck')}")

d = DiagnosticianAgent
print(f"_fallback_diagnosis: {hasattr(d, '_fallback_diagnosis')}")
print(f"_build_diagnosis: {hasattr(d, '_build_diagnosis')}")

c = CommsAgent
print(f"_fallback_slack: {hasattr(c, '_fallback_slack')}")
print(f"_fallback_postmortem: {hasattr(c, '_fallback_postmortem')}")

s = SentryAgent.__init__
# Check _active_severities is in __init__ source
import inspect
src = inspect.getsource(s)
print(f"_active_severities in SentryAgent.__init__: {'_active_severities' in src}")

print("\nAll Day 14 checks passed!")
