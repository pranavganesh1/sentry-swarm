import threading
import logging
import time

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s %(message)s",
    datefmt="%H:%M:%S",
)

from agents.sentry import SentryAgent, SentryTrigger

def handle_incident(trigger: SentryTrigger):
    print(f"\n{'='*60}")
    print(f"  INCIDENT FIRED")
    print(f"  id       : {trigger.incident_id}")
    print(f"  type     : {trigger.incident_type}")
    print(f"  severity : {trigger.severity}")
    print(f"  services : {trigger.affected_services}")
    print(f"  summary  : {trigger.summary}")
    print(f"  mttd est : {(trigger.detected_at - trigger.started_at).seconds}s")
    print(f"{'='*60}\n")

    # simulate resolution after 20s so cooldown resets properly
    def resolve():
        time.sleep(20)
        agent.clear_incident(trigger.incident_type)
        print(f"[test] Incident {trigger.incident_id} cleared")

    threading.Thread(target=resolve, daemon=True).start()

agent = SentryAgent(on_incident=handle_incident)

print("[test] Starting Sentry Agent — run log_generator.py in another terminal")
print("[test] Waiting for a spike to fire (every ~60s from generator)...")
print("[test] Ctrl+C to stop\n")

agent.start()  # blocking
