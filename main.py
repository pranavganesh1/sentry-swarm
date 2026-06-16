import logging
import signal
import sys
import threading
from pathlib import Path

from orchestrator import IncidentOrchestrator
import dashboard_rich as dash


def configure_logging() -> None:
    Path("logs").mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(message)s",
        datefmt="%H:%M:%S",
        handlers=[
            logging.FileHandler("logs/orchestrator.log", encoding="utf-8"),
        ],
    )


def main() -> int:
    configure_logging()
    orchestrator = IncidentOrchestrator()

    def shutdown(sig, frame) -> None:
        orchestrator.stop()
        sys.exit(0)

    signal.signal(signal.SIGINT,  shutdown)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, shutdown)

    # start orchestrator in background thread
    orchestrator.start()

    # run Rich dashboard on main thread (blocks until Ctrl+C)
    dash.run_dashboard()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
