"""
reset_benchmark.py — Wipe all logs and metrics for a clean benchmark run.

Usage:
    python reset_benchmark.py
"""

from pathlib import Path


FILES_TO_CLEAR = [
    Path("logs/app.log"),
    Path("logs/events.db"),
    Path("logs/mttd_metrics.json"),
    Path("logs/benchmark_results.json"),
    Path("logs/active_incidents.json"),
    Path("logs/orchestrator.log"),
    Path("logs/commands.json"),
]


def reset():
    Path("logs").mkdir(parents=True, exist_ok=True)
    removed = 0
    for path in FILES_TO_CLEAR:
        if path.exists():
            try:
                path.unlink()
                print(f"  ✓ Removed {path}")
                removed += 1
            except OSError as e:
                print(f"  ✗ Could not remove {path}: {e}")
        else:
            print(f"  – {path} (not present)")
    print(f"\nDone — {removed} file(s) cleared. Ready for a clean run.")


if __name__ == "__main__":
    print("Resetting benchmark state...\n")
    reset()
