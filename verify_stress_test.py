import re
from metrics import get_summary

def check_orchestrator_log():
    errors = []
    try:
        with open("logs/orchestrator.log") as f:
            for line in f:
                if "ERROR" in line or "Traceback" in line or "timed out" in line.lower():
                    errors.append(line.strip())
    except FileNotFoundError:
        print("No orchestrator.log found — did you run main.py?")
        return []
    return errors

def check_results():
    print("=" * 60)
    print("STRESS TEST RESULTS")
    print("=" * 60)

    summary = get_summary()
    recent = summary.get("records", [])[-5:]   # last 5 incidents

    print(f"\nTotal incidents recorded: {summary.get('total', 0)}")
    print(f"Average MTTD: {summary.get('avg_mttd', 0):.1f}s")

    print(f"\nLast {len(recent)} incidents:")
    for r in recent:
        print(f"  {r['incident_id']} | {r['incident_type']:<12} | "
              f"mttd={r['mttd_seconds']:.1f}s | status={r['status']}")

    types_seen = {r["incident_type"] for r in recent}
    expected = {"http_5xx", "db_timeout", "oom_kill"}
    missing = expected - types_seen

    print(f"\nExpected types: {expected}")
    print(f"Types seen: {types_seen}")
    if missing:
        print(f"⚠ MISSING: {missing} — these incidents were not processed!")
    else:
        print("✓ All 3 incident types were detected and processed")

    errors = check_orchestrator_log()
    print(f"\nErrors found in orchestrator.log: {len(errors)}")
    for e in errors[-10:]:
        print(f"  {e}")

    if not errors and not missing:
        print("\n✅ STRESS TEST PASSED")
    else:
        print("\n❌ STRESS TEST FAILED — see issues above")

if __name__ == "__main__":
    check_results()
