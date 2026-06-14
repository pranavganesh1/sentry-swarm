import unittest
from datetime import datetime, timedelta
from types import SimpleNamespace

from agents.diagnostician import DiagnosticianAgent


class DiagnosticianTests(unittest.TestCase):
    def test_builds_incident_state_and_calculates_mttd(self) -> None:
        detected_at = datetime.now()
        trigger = SimpleNamespace(
            incident_id="incident-1",
            incident_type="oom_kill",
            severity="high",
            affected_services=["payments"],
            confidence=0.95,
            summary="Payments pods are being OOM killed",
            trigger_events=[
                {"message": "Process killed by OOM killer"},
                {"message": "upstream connection refused"},
            ],
            started_at=detected_at - timedelta(seconds=7.25),
            detected_at=detected_at,
        )

        state = DiagnosticianAgent().run(trigger)

        self.assertEqual(state.incident_id, "incident-1")
        self.assertEqual(state.status, "diagnosed")
        self.assertEqual(state.mttd_seconds, 7.25)
        self.assertIn("oom_kill.md", state.diagnosis)
        self.assertIn("Process killed by OOM killer", state.diagnosis)


if __name__ == "__main__":
    unittest.main()
