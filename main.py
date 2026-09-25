import logging
import signal
import sys
import threading
from pathlib import Path

import health_check
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
            logging.StreamHandler(sys.stdout)
        ],
    )


def main() -> int:
    try:
        # Run pre-flight checks
        health_check.run_diagnostics()

        configure_logging()
        logger = logging.getLogger(__name__)
        logger.info("Starting DevOps Incident Response System")

        orchestrator = IncidentOrchestrator()

        def shutdown(sig, frame) -> None:
            logger.info("Received shutdown signal, stopping orchestrator...")
            orchestrator.stop()
            sys.exit(0)

        signal.signal(signal.SIGINT,  shutdown)
        if hasattr(signal, "SIGTERM"):
            signal.signal(signal.SIGTERM, shutdown)

        # start orchestrator in background thread
        orchestrator.start()
        logger.info("Orchestrator started successfully")

        # run Rich dashboard on main thread (blocks until Ctrl+C)
        dash.run_dashboard()

        return 0
    except Exception as e:
        logging.error(f"Failed to start system: {e}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
