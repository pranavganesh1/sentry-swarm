import threading
import time
import unittest
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import patch

from orchestrator import IncidentOrchestrator
from state import IncidentState


class FakeSentry:
    def __init__(self) -> None:
        self.on_incident = None
        self.running = threading.Event()
        self.cleared: list[str] = []

    def start(self) -> None:
        self.running.set()
        while self.running.is_set():
            time.sleep(0.005)

    def stop(self) -> None:
        self.running.clear()

    def clear_incident(self, incident_type: str) -> None:
        self.cleared.append(incident_type)


class RecordingAgent:
    def __init__(self, name: str, calls: list[tuple[str, str]]) -> None:
        self.name = name
        self.calls = calls

    def run(self, value):
        incident_id = value.incident_id
        self.calls.append((incident_id, self.name))
        if self.name == "diagnostician":
            return IncidentState(
                incident_id=value.incident_id,
                incident_type=value.incident_type,
                severity=value.severity,
                affected_services=value.affected_services,
                trigger_events=value.trigger_events,
                started_at=value.started_at,
                detected_at=value.detected_at,
                mttd_seconds=5.0,
                diagnosis="diagnosed",
                status="diagnosed",
            )
        if self.name == "fix_planner":
            value.fix_plan = ["restart service"]
            value.status = "fix_planned"
        if self.name == "comms":
            value.comms_update = "resolved"
            value.status = "resolved"
        return value


def make_trigger(incident_id: str, incident_type: str):
    detected_at = datetime.now()
    return SimpleNamespace(
        incident_id=incident_id,
        incident_type=incident_type,
        severity="high",
        affected_services=["api"],
        confidence=0.9,
        summary="test incident",
        trigger_events=[],
        started_at=detected_at - timedelta(seconds=5),
        detected_at=detected_at,
    )


class OrchestratorTests(unittest.TestCase):
    def make_orchestrator(self):
        calls: list[tuple[str, str]] = []
        sentry = FakeSentry()
        orchestrator = IncidentOrchestrator(
            sentry=sentry,
            diagnostician=RecordingAgent("diagnostician", calls),
            fix_planner=RecordingAgent("fix_planner", calls),
            comms=RecordingAgent("comms", calls),
            agent_timeout_seconds=1,
        )
        return orchestrator, sentry, calls

    @patch("orchestrator.record_incident")
    def test_runs_agents_in_order_and_records_resolution(
        self, record_incident
    ) -> None:
        orchestrator, sentry, calls = self.make_orchestrator()
        completed = threading.Event()
        final_states = []

        def on_done(state) -> None:
            final_states.append(state)
            completed.set()

        orchestrator.on_incident_done = on_done
        orchestrator.start()
        try:
            self.assertTrue(
                orchestrator.inject_incident(
                    make_trigger("one", "oom_kill")
                )
            )
            self.assertTrue(completed.wait(timeout=2))
        finally:
            orchestrator.stop()

        self.assertEqual(
            calls,
            [
                ("one", "diagnostician"),
                ("one", "fix_planner"),
                ("one", "comms"),
            ],
        )
        self.assertEqual(final_states[0].status, "resolved")
        self.assertEqual(sentry.cleared, ["oom_kill"])
        record_incident.assert_called_once()

    @patch("orchestrator.record_incident")
    def test_queues_distinct_incidents_and_rejects_duplicates(
        self, _record_incident
    ) -> None:
        orchestrator, _sentry, calls = self.make_orchestrator()
        completed = threading.Event()
        completed_ids: list[str] = []

        def on_done(state) -> None:
            completed_ids.append(state.incident_id)
            if len(completed_ids) == 2:
                completed.set()

        orchestrator.on_incident_done = on_done
        first = make_trigger("one", "oom_kill")
        same_id = make_trigger("one", "db_timeout")
        same_type = make_trigger("two", "oom_kill")
        second = make_trigger("three", "db_timeout")

        self.assertTrue(orchestrator.inject_incident(first))
        self.assertFalse(orchestrator.inject_incident(same_id))
        self.assertFalse(orchestrator.inject_incident(same_type))
        self.assertTrue(orchestrator.inject_incident(second))

        orchestrator.start()
        try:
            self.assertTrue(completed.wait(timeout=2))
        finally:
            orchestrator.stop()

        self.assertCountEqual(completed_ids, ["one", "three"])
        self.assertEqual(len(calls), 6)


if __name__ == "__main__":
    unittest.main()
