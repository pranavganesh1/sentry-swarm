"""Day 14 — Lifecycle hardening integration test.

Run alongside log_generator.py and watcher.py to verify:
  - Normal incidents resolve cleanly through all 4 agents
  - LLM failures degrade to fallback instead of crashing
  - Stuck incidents (>180s) are force-closed by the watchdog
  - manually_resolve() works and clears cooldown immediately
"""

import logging
import time

from orchestrator import IncidentOrchestrator

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(message)s",
    datefmt="%H:%M:%S",
)

orchestrator = IncidentOrchestrator()
orchestrator.start()

print("[test] Orchestrator running with watchdog + retries + manual override")
print("[test] Run log_generator.py separately, then try:")
print("  - Ctrl+C to stop")
print("  - In another shell:")
print("      python -c \"from test_lifecycle import orchestrator; print(orchestrator.get_active_incidents())\"")
print()

try:
    while True:
        time.sleep(10)
        active = orchestrator.get_active_incidents()
        if active:
            for inc in active:
                age = time.time() - inc.started_at.timestamp()
                print(
                    f"[test] Active: {inc.incident_id} ({inc.incident_type}) "
                    f"age={age:.0f}s status={inc.status}"
                )
        else:
            print("[test] No active incidents")
except KeyboardInterrupt:
    print("\n[test] Stopping orchestrator...")
    orchestrator.stop()
    print("[test] Done.")
