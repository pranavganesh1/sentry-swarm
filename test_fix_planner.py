import unittest
from datetime import datetime
from unittest.mock import patch

from agents.fix_planner import FixPlannerAgent
from state import IncidentState


class FixPlannerTests(unittest.TestCase):
    @patch("agents.fix_planner.os.getenv")
    def test_builds_plan_from_matching_runbook(self, mock_getenv) -> None:
        mock_getenv.return_value = None
        state = IncidentState(
            incident_id="incident-2",
            incident_type="db_timeout",
            severity="high",
            affected_services=["db-proxy"],
            trigger_events=[],
            started_at=datetime.now(),
            diagnosis="Connection pool exhausted",
            status="diagnosed",
        )

        result = FixPlannerAgent().run(state)

        self.assertEqual(result.status, "fix_planned")
        self.assertEqual(result.fix_plan[0], "=== IMMEDIATE STEPS ===")
        self.assertIn("Kill long-running queries (PostgreSQL):", result.fix_plan)
        self.assertIn("=== FOLLOWUP STEPS ===", result.fix_plan)


if __name__ == "__main__":
    unittest.main()
