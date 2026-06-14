import json
import os
import threading
from datetime import datetime
from pathlib import Path

from state import IncidentState


METRICS_FILE = Path("logs/mttd_metrics.json")
_metrics_lock = threading.Lock()


def _load_unlocked() -> list[dict]:
    if not METRICS_FILE.exists():
        return []

    try:
        with METRICS_FILE.open(encoding="utf-8") as metrics_file:
            data = json.load(metrics_file)
    except (json.JSONDecodeError, OSError):
        return []

    return data if isinstance(data, list) else []


def _save_unlocked(records: list[dict]) -> None:
    METRICS_FILE.parent.mkdir(parents=True, exist_ok=True)
    temporary_file = METRICS_FILE.with_suffix(".tmp")
    with temporary_file.open("w", encoding="utf-8") as metrics_file:
        json.dump(records, metrics_file, indent=2)
    os.replace(temporary_file, METRICS_FILE)


def record_incident(state: IncidentState) -> None:
    now = datetime.now()
    record = {
        "incident_id": state.incident_id,
        "incident_type": state.incident_type,
        "severity": state.severity,
        "affected_services": state.affected_services,
        "started_at": state.started_at.isoformat(),
        "detected_at": (
            state.detected_at.isoformat() if state.detected_at else None
        ),
        "resolved_at": now.isoformat(),
        "mttd_seconds": state.mttd_seconds,
        "status": state.status,
        "logged_at": now.isoformat(),
    }

    with _metrics_lock:
        records = _load_unlocked()
        records.append(record)
        _save_unlocked(records)


def get_avg_mttd() -> float:
    with _metrics_lock:
        records = _load_unlocked()

    times = [
        record["mttd_seconds"]
        for record in records
        if record.get("mttd_seconds") is not None
    ]
    return round(sum(times) / len(times), 2) if times else 0.0


def get_summary() -> dict:
    with _metrics_lock:
        records = _load_unlocked()

    if not records:
        return {"total": 0, "avg_mttd": 0.0, "by_type": {}, "records": []}

    by_type: dict[str, list[float]] = {}
    all_times: list[float] = []
    for record in records:
        mttd = record.get("mttd_seconds")
        if mttd is None:
            continue
        all_times.append(mttd)
        by_type.setdefault(record["incident_type"], []).append(mttd)

    return {
        "total": len(records),
        "avg_mttd": (
            round(sum(all_times) / len(all_times), 2) if all_times else 0.0
        ),
        "by_type": {
            incident_type: round(sum(times) / len(times), 2)
            for incident_type, times in by_type.items()
        },
        "records": records,
    }
