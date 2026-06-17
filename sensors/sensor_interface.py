import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict


@dataclass
class PhysicalTrigger:
    incident_id: str
    incident_type: str  # e.g. "fire", "gas_leak", "vibration", "fall"
    severity: str
    source: str  # sensor device identifier
    payload: Dict[str, Any]
    started_at: datetime
    detected_at: datetime
    affected_services: list[str] = None
    trigger_events: list[str] = None
    confidence: float = 1.0
    summary: str = "Physical sensor event"


def ingest_payload(raw: str) -> PhysicalTrigger:
    """Parse a JSON payload from UNO Q and return a ``PhysicalTrigger``.

    Expected format (example)::
        {
            "device_id": "uno-q-01",
            "type": "fire",
            "severity": "high",
            "timestamp": "2026-06-17T15:55:00Z",
            "data": {"temperature": 78.5, "smoke": true}
        }
    """
    data: Dict[str, Any] = json.loads(raw)
    now = datetime.utcnow()
    return PhysicalTrigger(
        incident_id=f"phys-{data['device_id']}-{int(now.timestamp())}",
        incident_type=data["type"],
        severity=data.get("severity", "medium"),
        source=data["device_id"],
        payload=data.get("data", {}),
        started_at=now,
        detected_at=now,
        affected_services=[],
        trigger_events=[],
    )
