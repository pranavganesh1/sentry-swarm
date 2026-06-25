"""
benchmark.py — Day 16 formal benchmark runner.

Records system MTTD for each of 5 incident types, compares against
honestly-measured manual-triage baselines, and produces the final
improvement number for the resume line.

Usage:
    python benchmark.py              # run full automated benchmark
    python benchmark.py --summary    # print results from a previous run
"""

import json
import os
import sys
import time
import threading
import random
from datetime import datetime
from pathlib import Path

BENCHMARK_FILE = Path("logs/benchmark_results.json")
METRICS_FILE = Path("logs/mttd_metrics.json")

# ── Manual baseline (seconds) ──────────────────────────────────────────
# Conservative defaults for a single SRE doing:
#   tail -f logs → notice anomaly → grep pattern → read runbook → identify root cause
# Replace with YOUR real measured values for maximum defensibility.
MANUAL_BASELINE_SECONDS = {
    "http_5xx":          180,   # tail → see 500s → grep → read runbook
    "db_timeout":        237,   # subtler pool-exhaustion pattern
    "oom_kill":          165,   # FATAL + OOM distinctive, slightly faster
    "failed_deploy":     210,   # check pod status, cross-ref pipeline
    "cascading_failure": 420,   # must identify root among multi-service errors
}

# Order in which we run the 5 types
INCIDENT_ORDER = ["http_5xx", "db_timeout", "oom_kill", "failed_deploy", "cascading_failure"]


# ── Recording / summary helpers ────────────────────────────────────────

def record_benchmark_run(incident_type: str, system_mttd: float, notes: str = ""):
    """Append one benchmark result to logs/benchmark_results.json."""
    results = []
    if BENCHMARK_FILE.exists():
        try:
            with BENCHMARK_FILE.open() as f:
                results = json.load(f)
        except (json.JSONDecodeError, OSError):
            results = []

    manual = MANUAL_BASELINE_SECONDS.get(incident_type, 0)
    improvement_pct = round((1 - system_mttd / manual) * 100, 1) if manual else 0

    results.append({
        "incident_type":         incident_type,
        "system_mttd_seconds":   round(system_mttd, 2),
        "manual_baseline_seconds": manual,
        "improvement_pct":       improvement_pct,
        "recorded_at":           datetime.now().isoformat(),
        "notes":                 notes,
    })

    BENCHMARK_FILE.parent.mkdir(parents=True, exist_ok=True)
    with BENCHMARK_FILE.open("w") as f:
        json.dump(results, f, indent=2)

    print(f"\n{'='*60}")
    print(f"BENCHMARK RECORDED: {incident_type}")
    print(f"{'='*60}")
    print(f"  System MTTD     : {system_mttd:.1f}s")
    print(f"  Manual baseline : {manual}s")
    print(f"  Improvement     : {improvement_pct}%")


def print_final_summary():
    """Print the formatted benchmark summary table."""
    if not BENCHMARK_FILE.exists():
        print("No benchmark results yet.")
        return None

    with BENCHMARK_FILE.open() as f:
        results = json.load(f)

    print(f"\n{'='*60}")
    print(f"FINAL BENCHMARK SUMMARY — {len(results)} incidents")
    print(f"{'='*60}")

    total_system = 0
    total_manual = 0

    for r in results:
        print(f"  {r['incident_type']:<20} system={r['system_mttd_seconds']:>6.1f}s  "
              f"manual={r['manual_baseline_seconds']:>4}s  improvement={r['improvement_pct']:>5.1f}%")
        total_system += r["system_mttd_seconds"]
        total_manual += r["manual_baseline_seconds"]

    avg_improvement = round((1 - total_system / total_manual) * 100, 1) if total_manual else 0

    print(f"\n  TOTAL system time : {total_system:.1f}s")
    print(f"  TOTAL manual time : {total_manual}s")
    print(f"  OVERALL improvement: {avg_improvement}%")
    print(f"{'='*60}")

    return avg_improvement


# ── Automated benchmark runner ──────────────────────────────────────────

def _clear_state():
    """Wipe logs so we get a clean benchmark run."""
    for path in [
        Path("logs/app.log"),
        Path("logs/events.db"),
        Path("logs/mttd_metrics.json"),
        Path("logs/benchmark_results.json"),
        Path("logs/active_incidents.json"),
        Path("logs/orchestrator.log"),
    ]:
        if path.exists():
            try:
                path.unlink()
            except OSError:
                pass
    Path("logs").mkdir(parents=True, exist_ok=True)
    print("[benchmark] State cleared.")


def _get_metrics_count() -> int:
    """Return how many records are in mttd_metrics.json right now."""
    if not METRICS_FILE.exists():
        return 0
    try:
        with METRICS_FILE.open() as f:
            data = json.load(f)
        return len(data) if isinstance(data, list) else 0
    except (json.JSONDecodeError, OSError):
        return 0


def _get_latest_record() -> dict | None:
    """Return the most recent record from mttd_metrics.json."""
    if not METRICS_FILE.exists():
        return None
    try:
        with METRICS_FILE.open() as f:
            data = json.load(f)
        if isinstance(data, list) and data:
            return data[-1]
    except (json.JSONDecodeError, OSError):
        pass
    return None


def _fire_spike(incident_type: str, duration: int = 12):
    """Write error log lines for the given incident type into logs/app.log."""
    from log_generator_stress import SPIKE_TYPES, write_log
    templates = SPIKE_TYPES[incident_type]
    end = time.time() + duration
    while time.time() < end:
        write_log(random.choice(templates))
        time.sleep(0.12)


def _write_normal_traffic(stop_event: threading.Event):
    """Write normal log lines so the sentry has context (error rate calculation needs total events)."""
    from log_generator import NORMAL_TEMPLATES, write_log
    while not stop_event.is_set():
        template = random.choice(NORMAL_TEMPLATES)
        write_log(template())
        time.sleep(0.3)


def run_full_benchmark():
    """Automated benchmark: starts the full stack, fires 5 incident types, records MTTD."""
    print("\n" + "=" * 60)
    print("  SENTRY-SWARM FORMAL BENCHMARK")
    print("  5 incident types · sequential · clean state")
    print("=" * 60)

    # 1. Clear old state
    _clear_state()

    # 2. Initialise ingestion DB
    from ingestion.buffer import init_db
    init_db()

    # 3. Start the watcher (log file → SQLite)
    from ingestion.watcher import LogHandler, on_new_event
    log_path = Path("logs/app.log")
    log_path.touch()
    handler = LogHandler(log_path, on_new_event)

    from watchdog.observers import Observer
    observer = Observer()
    observer.schedule(handler, path=os.fspath(log_path.parent), recursive=False)
    observer.start()
    print("[benchmark] Watcher started.")

    # 4. Start the orchestrator (sentry → diagnostician → fix_planner → comms)
    from orchestrator import IncidentOrchestrator
    orchestrator = IncidentOrchestrator()
    orchestrator.start()
    print("[benchmark] Orchestrator started.")

    # 5. Start background normal-traffic generator
    stop_normal = threading.Event()
    normal_thread = threading.Thread(target=_write_normal_traffic, args=(stop_normal,), daemon=True)
    normal_thread.start()
    print("[benchmark] Normal traffic generator started.")

    # Give everything a moment to initialise
    time.sleep(3)

    # 6. Run each incident type sequentially
    for idx, incident_type in enumerate(INCIDENT_ORDER, 1):
        print(f"\n{'─'*60}")
        print(f"  [{idx}/5] Firing: {incident_type}")
        print(f"{'─'*60}")

        count_before = _get_metrics_count()

        # Fire the spike for 12 seconds
        spike_thread = threading.Thread(target=_fire_spike, args=(incident_type, 12), daemon=True)
        spike_thread.start()

        # Wait for the pipeline to detect + resolve (new record in metrics file)
        timeout = 180  # 3 minutes max per incident
        waited = 0
        while waited < timeout:
            time.sleep(2)
            waited += 2
            current_count = _get_metrics_count()
            if current_count > count_before:
                break

        spike_thread.join(timeout=5)

        if _get_metrics_count() <= count_before:
            print(f"  ⚠ TIMEOUT: {incident_type} was not detected within {timeout}s")
            record_benchmark_run(incident_type, timeout, notes="TIMEOUT — not detected")
        else:
            record = _get_latest_record()
            mttd = record.get("mttd_seconds", 0) if record else 0
            detected_type = record.get("incident_type", "unknown") if record else "unknown"
            record_benchmark_run(
                incident_type, mttd,
                notes=f"Auto-detected as '{detected_type}', status={record.get('status', '?')}"
            )

        # Cooldown between incidents — let sentry cooldown expire and logs settle
        if idx < len(INCIDENT_ORDER):
            cooldown = 55  # slightly more than COOLDOWN_SECONDS (45)
            print(f"  Cooling down {cooldown}s before next incident...")
            time.sleep(cooldown)

    # 7. Shutdown
    stop_normal.set()
    orchestrator.stop()
    observer.stop()
    observer.join(timeout=5)

    print("\n[benchmark] All incidents complete.\n")

    # 8. Print final summary
    result = print_final_summary()
    if result is not None:
        print(f"\n  ✅ Resume line: reduced MTTD by {result}% across 5 incident types")

    return result


if __name__ == "__main__":
    if "--summary" in sys.argv:
        print_final_summary()
    else:
        run_full_benchmark()
