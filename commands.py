"""
File-based command queue for cross-process communication.

Streamlit (or any external process) submits commands via submit_command().
The orchestrator polls for pending commands via get_pending_commands() and
marks them done with mark_processed().
"""

import json
import os
from datetime import datetime

COMMANDS_FILE = "logs/commands.json"


def _read_commands() -> list[dict]:
    if not os.path.exists(COMMANDS_FILE):
        return []
    try:
        with open(COMMANDS_FILE) as f:
            return json.load(f)
    except (json.JSONDecodeError, FileNotFoundError):
        return []


def _write_commands(commands: list[dict]):
    os.makedirs("logs", exist_ok=True)
    with open(COMMANDS_FILE, "w") as f:
        json.dump(commands, f, indent=2)


def submit_command(action: str, incident_id: str, reason: str = ""):
    """Called by Streamlit (or any external process) to queue a command."""
    commands = _read_commands()
    commands.append({
        "action":       action,        # "resolve" | "cancel"
        "incident_id":  incident_id,
        "reason":       reason,
        "submitted_at": datetime.now().isoformat(),
        "processed":    False,
    })
    _write_commands(commands)


def get_pending_commands() -> list[dict]:
    """Called by orchestrator to fetch unprocessed commands."""
    commands = _read_commands()
    return [c for c in commands if not c["processed"]]


def mark_processed(submitted_at: str):
    """Mark a command as processed by its submitted_at timestamp."""
    commands = _read_commands()
    for c in commands:
        if c["submitted_at"] == submitted_at:
            c["processed"] = True
    _write_commands(commands)
