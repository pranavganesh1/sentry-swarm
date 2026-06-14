import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import metrics
from state import IncidentState


class MetricsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        metrics_path = Path(self.temporary_directory.name) / "metrics.json"
        self.metrics_file_patch = patch.object(
            metrics, "METRICS_FILE", metrics_path
        )
        self.metrics_file_patch.start()

    def tearDown(self) -> None:
        self.metrics_file_patch.stop()
        self.temporary_directory.cleanup()

    def make_state(
        self, incident_id: str, incident_type: str, mttd_seconds: float
    ) -> IncidentState:
        detected_at = datetime.now()
        return IncidentState(
            incident_id=incident_id,
            incident_type=incident_type,
            severity="high",
            affected_services=["api"],
            trigger_events=[],
            started_at=detected_at - timedelta(seconds=mttd_seconds),
            detected_at=detected_at,
            mttd_seconds=mttd_seconds,
            status="resolved",
        )

    def test_records_incidents_and_summarizes_mttd(self) -> None:
        metrics.record_incident(self.make_state("one", "oom_kill", 8.0))
        metrics.record_incident(self.make_state("two", "oom_kill", 12.0))
        metrics.record_incident(self.make_state("three", "db_timeout", 10.0))

        summary = metrics.get_summary()

        self.assertEqual(summary["total"], 3)
        self.assertEqual(summary["avg_mttd"], 10.0)
        self.assertEqual(
            summary["by_type"], {"oom_kill": 10.0, "db_timeout": 10.0}
        )
        self.assertEqual(summary["records"][0]["incident_id"], "one")

    def test_empty_summary_has_stable_shape(self) -> None:
        self.assertEqual(
            metrics.get_summary(),
            {"total": 0, "avg_mttd": 0.0, "by_type": {}, "records": []},
        )


if __name__ == "__main__":
    unittest.main()
