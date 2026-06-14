import logging
import signal
import sys
import time
from pathlib import Path

from orchestrator import IncidentOrchestrator


def configure_logging() -> None:
    Path("logs").mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(message)s",
        datefmt="%H:%M:%S",
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler(
                "logs/orchestrator.log", encoding="utf-8"
            ),
        ],
    )


def main() -> int:
    configure_logging()
    orchestrator = IncidentOrchestrator()
    shutdown_requested = False

    def shutdown(_signal_number, _frame) -> None:
        nonlocal shutdown_requested
        if shutdown_requested:
            return
        shutdown_requested = True
        print("\n[main] Shutting down...")
        orchestrator.stop()

    signal.signal(signal.SIGINT, shutdown)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, shutdown)

    orchestrator.start()
    print("[main] Incident Response Commander running")
    print("[main] Make sure log_generator.py and watcher.py are running")
    print("[main] Ctrl+C to stop\n")

    try:
        while not shutdown_requested:
            time.sleep(5)
            active = orchestrator.get_active_incidents()
            if active:
                incident_ids = [
                    incident.incident_id for incident in active
                ]
                print(f"[main] Active incidents: {incident_ids}")
    finally:
        orchestrator.stop()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
