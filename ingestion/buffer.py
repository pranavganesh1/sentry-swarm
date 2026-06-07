import sqlite3
from pathlib import Path
from typing import Any

from ingestion.parser import LogEvent


DB_PATH = Path("logs/events.db")


def _connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(exist_ok=True)
    return sqlite3.connect(DB_PATH)


def init_db() -> None:
    with _connect() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                level TEXT NOT NULL,
                service TEXT NOT NULL,
                message TEXT NOT NULL,
                incident_type TEXT,
                raw TEXT NOT NULL,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS incidents (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                incident_type TEXT NOT NULL,
                started_at TEXT NOT NULL,
                resolved_at TEXT,
                status TEXT DEFAULT 'open'
            )
            """
        )


def insert_event(event: LogEvent) -> None:
    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO events (timestamp, level, service, message, incident_type, raw)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                event.timestamp.strftime("%Y-%m-%d %H:%M:%S"),
                event.level,
                event.service,
                event.message,
                event.incident_type,
                event.raw,
            ),
        )


def get_recent_events(limit: int = 50) -> list[dict[str, Any]]:
    with _connect() as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT * FROM events ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [dict(row) for row in reversed(rows)]


def get_error_events(since_seconds: int = 30) -> list[dict[str, Any]]:
    with _connect() as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """
            SELECT *
            FROM events
            WHERE level IN ('ERROR', 'FATAL')
              AND datetime(timestamp) >= datetime('now', ? || ' seconds')
            ORDER BY id ASC
            """,
            (f"-{since_seconds}",),
        ).fetchall()
    return [dict(row) for row in rows]


def get_error_rate(since_seconds: int = 30) -> float:
    with _connect() as conn:
        total = conn.execute(
            """
            SELECT COUNT(*)
            FROM events
            WHERE datetime(timestamp) >= datetime('now', ? || ' seconds')
            """,
            (f"-{since_seconds}",),
        ).fetchone()[0]

        errors = conn.execute(
            """
            SELECT COUNT(*)
            FROM events
            WHERE level IN ('ERROR', 'FATAL')
              AND datetime(timestamp) >= datetime('now', ? || ' seconds')
            """,
            (f"-{since_seconds}",),
        ).fetchone()[0]

    if total == 0:
        return 0.0
    return round(errors / total * 100, 2)


def get_events_by_type(incident_type: str, since_seconds: int = 60) -> list[dict]:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    rows = conn.execute("""
        SELECT * FROM events
        WHERE incident_type = ?
        AND datetime(timestamp) >= datetime('now', ? || ' seconds')
        ORDER BY id ASC
    """, (incident_type, f"-{since_seconds}")).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_recent_events_mixed(since_seconds: int = 30) -> list[dict[str, Any]]:
    """Returns both normal and error events for the classifier to see full context."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    rows = conn.execute("""
        SELECT * FROM events
        WHERE datetime(timestamp) >= datetime('now', ? || ' seconds')
        ORDER BY id ASC
    """, (f"-{since_seconds}",)).fetchall()
    conn.close()
    return [dict(r) for r in rows]
