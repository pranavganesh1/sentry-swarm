import logging

from agents.comms import CommsAgent
from agents.sentry import SentryAgent


try:
    from agents.diagnostician import DiagnosticianAgent
    from agents.fix_planner import FixPlannerAgent
except ModuleNotFoundError as exc:
    missing_agent = exc.name or "an earlier Day agent"
    raise SystemExit(
        "[pipeline] Missing dependency: "
        f"{missing_agent}. Add the diagnostician and fix planner agents before "
        "running the full four-agent pipeline."
    ) from exc


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(message)s",
    datefmt="%H:%M:%S",
)


def handle_incident(trigger):
    print(f"\n[pipeline] Sentry fired: {trigger.incident_type}")

    state = DiagnosticianAgent().run(trigger)
    print(f"[pipeline] Diagnosed: {state.diagnosis.splitlines()[0]}")

    state = FixPlannerAgent().run(state)
    print(f"[pipeline] Fix plan ready: {len(state.fix_plan)} lines")

    state = CommsAgent().run(state)
    print(f"\n[pipeline] SLACK UPDATE:\n{state.comms_update}")
    print("\n[pipeline] Post-mortem saved")
    print(f"[pipeline] MTTD: {state.mttd_seconds}s | Status: {state.status}")


sentry = SentryAgent(on_incident=handle_incident)
print("[pipeline] Full four-agent pipeline running...")
print("[pipeline] Make sure log_generator.py and ingestion/watcher.py are running\n")
sentry.start()
