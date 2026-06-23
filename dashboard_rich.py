import sys
import time
import threading
import logging
from datetime import datetime
from collections import deque

from rich.console import Console
from rich.layout import Layout
from rich.panel import Panel
from rich.table import Table
from rich.live import Live
from rich.text import Text
from rich.columns import Columns
from rich import box

from state import IncidentState
from metrics import get_summary
from commands import submit_command

console = Console()

# ── shared state (written by orchestrator callbacks, read by dashboard) ──
_log_lines: deque[str]           = deque(maxlen=30)
_active_incidents: dict[str, dict] = {}   # incident_id → render data
_timeline: deque[str]            = deque(maxlen=40)
_lock = threading.Lock()

# ── severity colors ──
SEVERITY_COLOR = {
    "critical": "red",
    "high":     "orange1",
    "medium":   "yellow",
    "low":      "green",
}

# ── agent step labels ──
STEPS = ["sentry", "diagnostician", "fix_planner", "comms"]
STEP_LABELS = {
    "sentry":        "🛡  Sentry",
    "diagnostician": "🔍 Diagnostician",
    "fix_planner":   "🔧 Fix-Planner",
    "comms":         "📣 Comms",
}


# ── public write API (called by orchestrator callbacks) ──────────────────

def add_log_line(line: str):
    with _lock:
        ts = datetime.now().strftime("%H:%M:%S")
        _log_lines.append(f"[dim]{ts}[/dim] {line}")


def add_timeline_event(text: str):
    with _lock:
        ts = datetime.now().strftime("%H:%M:%S")
        _timeline.append(f"[dim]{ts}[/dim]  {text}")


def open_incident(state: IncidentState):
    with _lock:
        _active_incidents[state.incident_id] = {
            "incident_id":   state.incident_id,
            "incident_type": state.incident_type,
            "severity":      state.severity,
            "services":      state.affected_services,
            "started_at":    state.started_at,
            "current_step":  "diagnostician",
            "steps_done":    [],
            "status":        "active",
            "mttd":          None,
        }
    add_timeline_event(
        f"[bold orange1]🚨 INCIDENT {state.incident_id}[/bold orange1] "
        f"[yellow]{state.incident_type}[/yellow] | "
        f"severity={state.severity}"
    )


def update_incident_step(incident_id: str, step: str, done: bool = False):
    with _lock:
        if incident_id not in _active_incidents:
            return
        inc = _active_incidents[incident_id]
        if done:
            inc["steps_done"].append(step)
            # advance to next step
            remaining = [s for s in STEPS if s not in inc["steps_done"]]
            inc["current_step"] = remaining[0] if remaining else "done"
        else:
            inc["current_step"] = step
    add_timeline_event(
        f"  [cyan]{STEP_LABELS.get(step, step)}[/cyan] "
        f"{'✓ complete' if done else '→ running'} for {incident_id}"
    )


def close_incident(state: IncidentState):
    with _lock:
        if state.incident_id in _active_incidents:
            _active_incidents[state.incident_id]["status"]     = "resolved"
            _active_incidents[state.incident_id]["mttd"]       = state.mttd_seconds
            _active_incidents[state.incident_id]["steps_done"] = list(STEPS)
    add_timeline_event(
        f"[bold green]✓ RESOLVED {state.incident_id}[/bold green] "
        f"mttd=[bold]{state.mttd_seconds:.1f}s[/bold]"
    )
    # clean up after 30s so it doesn't linger forever
    def _cleanup():
        time.sleep(30)
        with _lock:
            _active_incidents.pop(state.incident_id, None)
    threading.Thread(target=_cleanup, daemon=True).start()


# ── render helpers ────────────────────────────────────────────────────────

def _render_header() -> Panel:
    now = datetime.now().strftime("%Y-%m-%d  %H:%M:%S")
    title    = Text("⚡ Incident Response Commander", style="bold white")
    subtitle = Text(f"  {now}", style="dim")
    return Panel(
        Columns([title, subtitle], expand=True),
        style="bold blue",
        box=box.HEAVY,
        padding=(0, 1),
    )


def _render_metrics() -> Panel:
    summary = get_summary()
    table = Table(box=None, show_header=False, padding=(0, 2))
    table.add_column(style="dim")
    table.add_column(style="bold cyan")

    table.add_row("Total incidents", str(summary.get("total", 0)))
    table.add_row("Avg MTTD",        f"{summary.get('avg_mttd', 0):.1f}s")
    table.add_row(
        "Active now",
        str(len([i for i in _active_incidents.values() if i["status"] == "active"]))
    )

    by_type = summary.get("by_type", {})
    for itype, avg in by_type.items():
        table.add_row(f"  {itype}", f"{avg:.1f}s avg")

    return Panel(table, title="[bold]Metrics[/bold]", border_style="cyan", padding=(0, 1))


def _render_active_incidents() -> Panel:
    with _lock:
        incidents = list(_active_incidents.values())

    if not incidents:
        return Panel(
            Text("No active incidents", style="dim green"),
            title="[bold]Active Incidents[/bold]",
            border_style="green",
            padding=(1, 1),
        )

    table = Table(box=box.SIMPLE, show_header=True, header_style="bold dim", padding=(0, 1))
    table.add_column("ID",       width=10)
    table.add_column("Type",     width=18)
    table.add_column("Severity", width=10)
    table.add_column("Services", width=28)
    table.add_column("Pipeline", width=36)
    table.add_column("MTTD",     width=8)

    for inc in incidents:
        sev_color = SEVERITY_COLOR.get(inc["severity"], "white")
        severity  = Text(inc["severity"], style=f"bold {sev_color}")
        services  = ", ".join(inc["services"])[:26]

        # build pipeline progress bar
        pipeline_parts = []
        for step in STEPS:
            label = STEP_LABELS[step].split(" ", 1)[-1][:6]
            if step in inc["steps_done"]:
                pipeline_parts.append(f"[green]{label}✓[/green]")
            elif step == inc["current_step"] and inc["status"] == "active":
                pipeline_parts.append(f"[yellow bold]{label}…[/yellow bold]")
            else:
                pipeline_parts.append(f"[dim]{label}[/dim]")
        pipeline = " → ".join(pipeline_parts)

        mttd        = f"{inc['mttd']:.1f}s" if inc["mttd"] else "—"
        status_color = "green" if inc["status"] == "resolved" else "yellow"
        id_text      = Text(inc["incident_id"], style=f"bold {status_color}")

        table.add_row(id_text, inc["incident_type"], severity, services, pipeline, mttd)

    return Panel(table, title="[bold]Active Incidents[/bold]", border_style="yellow", padding=(0, 1))


def _render_log_tail() -> Panel:
    with _lock:
        lines = list(_log_lines)

    content = "\n".join(lines[-20:]) if lines else "[dim]Waiting for logs...[/dim]"
    return Panel(
        content,
        title="[bold]Live Log Tail[/bold]",
        border_style="dim",
        padding=(0, 1),
    )


def _render_timeline() -> Panel:
    with _lock:
        events = list(_timeline)

    content = "\n".join(events[-20:]) if events else "[dim]No events yet...[/dim]"
    return Panel(
        content,
        title="[bold]Incident Timeline[/bold]",
        border_style="magenta",
        padding=(0, 1),
    )


def _build_layout() -> Layout:
    layout = Layout()
    layout.split_column(
        Layout(name="header",  size=3),
        Layout(name="top",     size=8),
        Layout(name="middle",  size=12),
        Layout(name="bottom",  minimum_size=16),
    )
    layout["top"].split_row(
        Layout(name="metrics", size=32),
        Layout(name="active",  ratio=1),
    )
    layout["bottom"].split_row(
        Layout(name="logs",     ratio=1),
        Layout(name="timeline", ratio=1),
    )
    return layout


# ── log file tailer (feeds the live log panel from logs/app.log) ─────────

def _tail_log_file(filepath: str = "logs/app.log"):
    import os
    pos = 0
    while True:
        try:
            size = os.path.getsize(filepath)
            if size > pos:
                with open(filepath, encoding="utf-8", errors="replace") as f:
                    f.seek(pos)
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        if "ERROR" in line or "FATAL" in line:
                            add_log_line(f"[red]{line[:100]}[/red]")
                        elif "WARN" in line:
                            add_log_line(f"[yellow]{line[:100]}[/yellow]")
                        else:
                            add_log_line(f"[dim]{line[:100]}[/dim]")
                    pos = f.tell()
        except FileNotFoundError:
            pass
        time.sleep(0.5)


# ── main dashboard loop ───────────────────────────────────────────────────

def _input_listener():
    """Listens for 'r <incident_id>' or 'c <incident_id>' typed in the terminal."""
    print(
        "\n[dashboard] Type 'r <incident_id>' to resolve, "
        "'c <incident_id>' to cancel, then Enter.\n"
    )
    while True:
        try:
            line = input().strip()
        except EOFError:
            break
        if not line:
            continue
        parts = line.split()
        if len(parts) != 2:
            continue
        cmd, incident_id = parts
        if cmd == "r":
            submit_command(
                "resolve", incident_id,
                reason="Manually resolved via Rich dashboard",
            )
            add_timeline_event(
                f"[bold yellow]Manual resolve sent for {incident_id}[/bold yellow]"
            )
        elif cmd == "c":
            submit_command(
                "cancel", incident_id,
                reason="Cancelled via Rich dashboard",
            )
            add_timeline_event(
                f"[bold red]Manual cancel sent for {incident_id}[/bold red]"
            )


def run_dashboard():
    layout = _build_layout()

    # start background threads
    threading.Thread(target=_tail_log_file, daemon=True).start()
    threading.Thread(target=_input_listener, daemon=True).start()

    add_timeline_event("[bold cyan]Dashboard started[/bold cyan]")

    with Live(layout, console=console, refresh_per_second=2, screen=True):
        while True:
            layout["header"].update(_render_header())
            layout["metrics"].update(_render_metrics())
            layout["active"].update(_render_active_incidents())
            layout["logs"].update(_render_log_tail())
            layout["timeline"].update(_render_timeline())
            time.sleep(0.5)


if __name__ == "__main__":
    run_dashboard()
