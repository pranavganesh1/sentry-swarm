import unittest
from unittest.mock import patch, MagicMock
from datetime import datetime

from agents.fix_planner import FixPlannerAgent, GeneratedFixPlan
from state import IncidentState


class FixPlannerLLMTests(unittest.TestCase):
    @patch("agents.fix_planner.os.getenv")
    def test_fallback_when_no_api_key(self, mock_getenv) -> None:
        # Mock environment to simulate no Google API Key
        mock_getenv.return_value = None

        state = IncidentState(
            incident_id="test-fallback-id",
            incident_type="oom_kill",
            severity="critical",
            affected_services=["frontend"],
            trigger_events=[],
            started_at=datetime.now(),
            diagnosis="Out of Memory Kill detected",
            status="diagnosed",
        )

        result = FixPlannerAgent().run(state)

        # Check status and structure of fallback output
        self.assertEqual(result.status, "fix_planned")
        self.assertEqual(result.fix_plan[0], "=== IMMEDIATE STEPS ===")
        # Should contain some remediation steps from oom_kill.md
        self.assertTrue(any("kubectl rollout restart" in line for line in result.fix_plan))
        self.assertTrue(any("=== FOLLOWUP STEPS ===" in line for line in result.fix_plan))

    @patch("agents.fix_planner.os.getenv")
    @patch("agents.fix_planner._invoke_planner")
    def test_llm_generation_success(self, mock_invoke, mock_getenv) -> None:
        # Mock API key to be present
        mock_getenv.return_value = "fake-api-key"

        # Mock LLM output
        mock_response = GeneratedFixPlan(
            immediate_steps=["$ kubectl scale deployment/auth --replicas=5", "Verify routing table"],
            followup_steps=["Monitor memory consumption metrics", "Escalate to team if alerts trigger"],
            safety_guidelines=["Scaling up auth pods might saturate DB connection pools"]
        )
        mock_invoke.return_value = mock_response

        state = IncidentState(
            incident_id="test-llm-id",
            incident_type="oom_kill",
            severity="critical",
            affected_services=["auth"],
            trigger_events=[{"timestamp": "2026-07-01T20:00:00", "service": "auth", "message": "OOM killer activated"}],
            started_at=datetime.now(),
            diagnosis="Auth pod memory leak",
            status="diagnosed",
        )

        result = FixPlannerAgent().run(state)

        # Verify LLM-based output mapping
        self.assertEqual(result.status, "fix_planned")
        self.assertIn("=== IMMEDIATE STEPS ===", result.fix_plan)
        self.assertIn("$ kubectl scale deployment/auth --replicas=5", result.fix_plan)
        self.assertIn("=== FOLLOWUP STEPS ===", result.fix_plan)
        self.assertIn("Monitor memory consumption metrics", result.fix_plan)
        self.assertIn("=== SAFETY & RISK GUIDELINES ===", result.fix_plan)
        self.assertIn("Scaling up auth pods might saturate DB connection pools", result.fix_plan)


if __name__ == "__main__":
    unittest.main()
