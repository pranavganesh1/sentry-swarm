"""
benchmark/run_benchmark.py — Day 16 formal benchmark runner.

Simulates all 5 incident types sequentially, measures the system's MTTD
against a realistic manual-debugging baseline, and produces the actual
defensible number for the resume line.

Usage:
    python benchmark/run_benchmark.py            # run full benchmark
    python benchmark/run_benchmark.py --summary   # reprint last results
"""

import json
import os
import random
import sys
import threading
import time
import logging
from datetime import datetime
from pathlib import Path

# ── Fix import paths ─────────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
os.chdir(PROJECT_ROOT)

from orchestrator import IncidentOrchestrator
from metrics import get_summary
from ingestion.buffer import init_db
from ingestion.watcher import LogHandler, on_new_event

# ── Config ───────────────────────────────────────────────────────────

LOG_FILE = Path("logs/app.log")
RESULTS_FILE = Path("benchmark/results.json")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(name)s %(message)s",
    datefmt="%H:%M:%S",
    handlers=[
        logging.FileHandler("logs/benchmark.log", mode="w"),
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger("benchmark")

# Manual baselines from manual_baseline.md, in seconds
MANUAL_BASELINE_SECONDS = {
    "http_5xx":          300,
    "db_timeout":        480,
    "oom_kill":          420,
    "failed_deploy":     240,
    "cascading_failure": 780,
}

# Spike templates — static strings that the parser can match
# (using the same templates as log_generator_stress.py)
SPIKE_TEMPLATES = {
    "http_5xx": [
        "ERROR [user-api] GET /api/orders 500 Internal Server Error",
        "ERROR [user-api] POST /api/checkout 503 Service Unavailable",
        "ERROR [user-api] Unhandled exception: NullPointerException at line 412",
    ],
    "db_timeout": [
        "ERROR [db-proxy] Connection timeout after 30000ms",
        "WARN  [db-proxy] Connection pool exhausted (50/50 connections used)",
        "ERROR [user-api] Failed to fetch user data: upstream db-proxy timeout",
        "ERROR [auth-service] Session validation failed: upstream db-proxy timeout",
    ],
    "oom_kill": [
        "WARN  [payment-service] Memory usage at 93% - approaching limit",
        "FATAL [payment-service] OutOfMemoryError: Java heap space",
        "ERROR [payment-service] Process killed by OOM killer (RSS: 1100MB)",
        "ERROR [nginx] upstream payment-service unavailable (connection refused)",
    ],
    "failed_deploy": [
        "ERROR [auth-service] Deploy pipeline failed: exit code 1",
        "ERROR [auth-service] Pod in CrashLoopBackOff (5 restarts)",
        "ERROR [auth-service] Health check returned 503 after deploy",
        "WARN  [nginx] upstream auth-service unavailable (0 ready replicas)",
    ],
    "cascading_failure": [
        "ERROR [db-proxy] Connection timeout after 30000ms",
        "ERROR [auth-service] Failed to authenticate request: upstream timeout",
        "ERROR [user-api] Connection refused: upstream auth-service unavailable",
        "FATAL [payment-service] Circuit breaker OPEN for auth-service",
        "ERROR [nginx] 503 Service Unavailable - dependency auth-service down",
    ],
}

# Normal traffic templates (keep the error rate calculation realistic)
NORMAL_TEMPLATES = [
    "INFO  [user-api] GET /api/orders 200 45ms",
    "INFO  [auth-service] User abc123 authenticated successfully",
    "DEBUG [db-proxy] DB query completed in 12ms",
    "INFO  [payment-service] POST /api/payments 201 89ms",
    "INFO  [nginx] GET /health 200 2ms",
]


# ── State cleaning ───────────────────────────────────────────────────

def clear_state():
    """Wipe logs/metrics so we get a clean benchmark run."""
    for path in [
        Path("logs/app.log"),
        Path("logs/events.db"),
        Path("logs/mttd_metrics.json"),
        Path("logs/benchmark_results.json"),
        Path("logs/active_incidents.json"),
        Path("logs/orchestrator.log"),
        Path("logs/commands.json"),
    ]:
        if path.exists():
            try:
                path.unlink()
            except OSError:
                pass
    Path("logs").mkdir(parents=True, exist_ok=True)
    print("[benchmark] State cleared.\n")


# ── Log injection ────────────────────────────────────────────────────

def write_log(line: str):
    """Write a single log line to the app log (same format as log_generator)."""
    LOG_FILE.parent.mkdir(exist_ok=True)
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(f"[{ts}] {line}\n")
        f.flush()


def inject_spike(incident_type: str, count: int = 14):
    """Inject error log lines for a specific incident type."""
    templates = SPIKE_TEMPLATES[incident_type]
    for _ in range(count):
        write_log(random.choice(templates))
        time.sleep(0.12)


def write_normal_traffic(stop_event: threading.Event):
    """Background thread: write normal log lines for error rate context."""
    while not stop_event.is_set():
        write_log(random.choice(NORMAL_TEMPLATES))
        time.sleep(0.3)


# ── Resolution polling ───────────────────────────────────────────────

def wait_for_resolution(incident_type: str, timeout: int = 120) -> dict | None:
    """Poll mttd_metrics.json until a new record for this incident_type appears."""
    summary_before = get_summary()
    ids_before = {r["incident_id"] for r in summary_before.get("records", [])}

    start = time.time()
    while time.time() - start < timeout:
        time.sleep(2)
        summary = get_summary()
        for r in summary.get("records", []):
            if r["incident_id"] not in ids_before and r["incident_type"] == incident_type:
                return r
    return None


# ── Main benchmark ───────────────────────────────────────────────────

def run_benchmark():
    print("=" * 70)
    print("  SENTRY-SWARM FORMAL BENCHMARK")
    print("  5 incident types · sequential · clean state")
    print("=" * 70)

    # 1. Clean start
    clear_state()
    init_db()
    LOG_FILE.touch()

    # 2. Start the watcher (log file → SQLite buffer)
    from watchdog.observers import Observer

    handler = LogHandler(LOG_FILE, on_new_event)
    observer = Observer()
    observer.schedule(handler, path=os.fspath(LOG_FILE.parent), recursive=False)
    observer.start()
    print("[benchmark] Watcher started.")

    # 3. Start the orchestrator (sentry → diagnostician → fix_planner → comms)
    orchestrator = IncidentOrchestrator()
    orchestrator.start()
    print("[benchmark] Orchestrator started.")

    # 4. Start background normal-traffic generator
    stop_normal = threading.Event()
    normal_thread = threading.Thread(
        target=write_normal_traffic, args=(stop_normal,), daemon=True
    )
    normal_thread.start()
    print("[benchmark] Normal traffic generator started.")

    # Give everything a moment to initialise
    time.sleep(3)

    results = []

    for idx, incident_type in enumerate(SPIKE_TEMPLATES.keys(), 1):
        print(f"\n{'-' * 70}")
        print(f"[benchmark] === [{idx}/5] Testing: {incident_type} ===")
        print(f"{'-' * 70}")

        print(f"[benchmark] Injecting spike ({incident_type})...")
        inject_spike(incident_type)

        print(f"[benchmark] Waiting for full pipeline resolution (timeout 120s)...")
        record = wait_for_resolution(incident_type, timeout=120)

        if record is None:
            print(f"[benchmark] WARNING: TIMEOUT -- {incident_type} did not resolve within 120s")
            results.append({
                "incident_type": incident_type,
                "ai_mttd_seconds": None,
                "manual_baseline_seconds": MANUAL_BASELINE_SECONDS[incident_type],
                "reduction_pct": None,
                "status": "timeout",
            })
        else:
            ai_mttd = record["mttd_seconds"]
            manual = MANUAL_BASELINE_SECONDS[incident_type]
            reduction_pct = round((1 - (ai_mttd / manual)) * 100, 1)
            detected_as = record.get("incident_type", "unknown")
            print(
                f"[benchmark] OK Resolved | AI MTTD={ai_mttd:.1f}s | "
                f"Manual baseline={manual}s | Reduction={reduction_pct}% | "
                f"Detected as: {detected_as}"
            )
            results.append({
                "incident_type": incident_type,
                "ai_mttd_seconds": round(ai_mttd, 1),
                "manual_baseline_seconds": manual,
                "reduction_pct": reduction_pct,
                "detected_as": detected_as,
                "status": "resolved",
            })

        # Cooldown between tests so incident types don't overlap
        if idx < len(SPIKE_TEMPLATES):
            cooldown = 55  # Must exceed sentry COOLDOWN_SECONDS (45s)
            print(f"[benchmark] Cooling down {cooldown}s before next test...")
            time.sleep(cooldown)

    # Shutdown
    stop_normal.set()
    orchestrator.stop()
    observer.stop()
    observer.join(timeout=5)

    save_results(results)
    print_summary(results)


def save_results(results: list[dict]):
    RESULTS_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(RESULTS_FILE, "w") as f:
        json.dump({
            "run_at": datetime.now().isoformat(),
            "results": results,
        }, f, indent=2)
    print(f"\n[benchmark] Results saved to {RESULTS_FILE}")


def print_summary(results: list[dict]):
    resolved = [r for r in results if r["status"] == "resolved"]
    print(f"\n{'=' * 70}")
    print(f"BENCHMARK SUMMARY")
    print(f"{'=' * 70}")
    print(f"{'Type':<20} {'AI MTTD':<12} {'Manual':<12} {'Reduction':<12} {'Status'}")
    print(f"{'-' * 70}")
    for r in results:
        ai = f"{r['ai_mttd_seconds']}s" if r["ai_mttd_seconds"] is not None else "—"
        reduction = f"{r['reduction_pct']}%" if r.get("reduction_pct") is not None else "—"
        print(
            f"{r['incident_type']:<20} {ai:<12} "
            f"{r['manual_baseline_seconds']}s{'':<7} "
            f"{reduction:<12} {r['status']}"
        )

    if resolved:
        avg_reduction = sum(r["reduction_pct"] for r in resolved) / len(resolved)
        avg_ai_mttd = sum(r["ai_mttd_seconds"] for r in resolved) / len(resolved)
        print(f"{'-' * 70}")
        print(f"Average AI MTTD: {avg_ai_mttd:.1f}s")
        print(f"Average reduction vs manual baseline: {avg_reduction:.1f}%")
        print(
            f'\nRESUME NUMBER: "{avg_reduction:.0f}% reduction in '
            f'mean-time-to-diagnosis"'
        )
        print(
            f"\n  Defensible framing: ~{avg_ai_mttd:.0f}s average diagnosis "
            f"time vs an estimated 4-13 minute manual baseline across "
            f"{len(resolved)} incident types - validated via automated benchmark."
        )
    else:
        print(
            "\nFAILED: No incidents resolved successfully -- "
            "debug before claiming any number"
        )


if __name__ == "__main__":
    if "--summary" in sys.argv:
        if RESULTS_FILE.exists():
            with open(RESULTS_FILE) as f:
                data = json.load(f)
            print_summary(data["results"])
        else:
            print("No results file found. Run the benchmark first.")
    else:
        run_benchmark()
