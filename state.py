from dataclasses import dataclass
from datetime import datetime
from typing import Optional


@dataclass
class IncidentState:
    incident_id: str
    incident_type: str
    severity: str
    affected_services: list[str]
    trigger_events: list[dict]
    started_at: datetime
    detected_at: Optional[datetime] = None
    diagnosis: Optional[str] = None
    fix_plan: Optional[list[str]] = None
    comms_update: Optional[str] = None
    post_mortem: Optional[str] = None
    status: str = "open"
    mttd_seconds: Optional[float] = None
