"""
Streamlit dashboard for the Incident Response System.

Displays live metrics, active incidents with manual resolve/cancel controls,
and MTTD trend charts. Reads state from JSON files written by the orchestrator.
"""

import json
import os
import time

import streamlit as st

from commands import submit_command
from metrics import get_summary

# ── page config ──────────────────────────────────────────────────────────

st.set_page_config(
    page_title="Incident Response Dashboard",
    page_icon="⚡",
    layout="wide",
)

ACTIVE_SNAPSHOT_FILE = "logs/active_incidents.json"


# ── auto-refresh via fragment ────────────────────────────────────────────

@st.fragment(run_every=5)
def live_dashboard():
    summary = get_summary()
    records = summary.get("records", [])

    # ── metrics row ──────────────────────────────────────────────────
    st.subheader("📊 Metrics")
    m1, m2, m3 = st.columns(3)
    m1.metric("Total Incidents", summary.get("total", 0))
    m2.metric("Avg MTTD", f"{summary.get('avg_mttd', 0):.1f}s")
    m3.metric("Incident Types", len(summary.get("by_type", {})))

    by_type = summary.get("by_type", {})
    if by_type:
        cols = st.columns(len(by_type))
        for col, (itype, avg) in zip(cols, by_type.items()):
            col.metric(itype, f"{avg:.1f}s avg")

    # ── simulate incident ────────────────────────────────────────────
    st.divider()
    st.subheader("🧪 Simulate an incident")
    st.caption(
        "Injects error log lines into `logs/app.log` for the chosen incident type. "
        "The watcher → sentry → classifier pipeline picks them up automatically."
    )
    sim_col1, sim_col2, sim_col3 = st.columns([2, 2, 2])
    sim_type = sim_col1.selectbox(
        "Type",
        ["http_5xx", "db_timeout", "oom_kill", "failed_deploy", "cascading_failure"],
        key="sim_type",
    )
    sim_duration = sim_col2.slider(
        "Duration (seconds)", min_value=5, max_value=30, value=10, key="sim_dur"
    )
    sim_col3.markdown("")  # spacer

    if st.button("🚀 Fire simulated incident", use_container_width=True):
        import threading
        from log_generator_stress import fire_spike

        t = threading.Thread(target=fire_spike, args=(sim_type, sim_duration), daemon=True)
        t.start()
        st.success(f"Spike **{sim_type}** firing for {sim_duration}s — watch the pipeline pick it up")

    # ── active incidents — manual control ────────────────────────────
    st.divider()
    st.subheader("🎛️ Active incidents — manual control")

    active_incidents = []
    if os.path.exists(ACTIVE_SNAPSHOT_FILE):
        try:
            with open(ACTIVE_SNAPSHOT_FILE) as f:
                active_incidents = json.load(f)
        except (json.JSONDecodeError, FileNotFoundError):
            active_incidents = []

    if not active_incidents:
        st.info("No active incidents right now.")
    else:
        for inc in active_incidents:
            with st.container(border=True):
                c1, c2, c3, c4 = st.columns([2, 2, 4, 2])
                c1.markdown(f"**{inc['incident_id']}**")
                c1.caption(inc["incident_type"])
                c2.markdown(f"`{inc['severity']}`")
                c2.caption(f"status: {inc['status']}")
                c3.caption(inc.get("diagnosis") or "Diagnosis pending...")
                with c4:
                    resolve_col, cancel_col = st.columns(2)
                    if resolve_col.button(
                        "✓ Resolve",
                        key=f"resolve_{inc['incident_id']}",
                        use_container_width=True,
                    ):
                        submit_command(
                            "resolve",
                            inc["incident_id"],
                            reason="Manually resolved from dashboard",
                        )
                        st.success(f"Resolve command sent for {inc['incident_id']}")
                        time.sleep(1)
                        st.rerun()
                    if cancel_col.button(
                        "✕ Cancel",
                        key=f"cancel_{inc['incident_id']}",
                        use_container_width=True,
                    ):
                        submit_command(
                            "cancel",
                            inc["incident_id"],
                            reason="Cancelled from dashboard",
                        )
                        st.warning(f"Cancel command sent for {inc['incident_id']}")
                        time.sleep(1)
                        st.rerun()

    # ── MTTD trend chart ─────────────────────────────────────────────
    st.divider()
    st.subheader("📈 MTTD Trend")
    if records:
        import pandas as pd

        df = pd.DataFrame(records)
        if "mttd_seconds" in df.columns and "resolved_at" in df.columns:
            df["resolved_at"] = pd.to_datetime(df["resolved_at"])
            df = df.dropna(subset=["mttd_seconds"])
            if not df.empty:
                st.line_chart(df.set_index("resolved_at")["mttd_seconds"])
            else:
                st.info("No MTTD data yet.")
        else:
            st.info("Waiting for incident data...")
    else:
        st.info("No incidents recorded yet.")

    # ── recent incident log ──────────────────────────────────────────
    st.divider()
    st.subheader("📋 Recent Incidents")
    if records:
        import pandas as pd

        df = pd.DataFrame(records)
        display_cols = [
            c for c in [
                "incident_id", "incident_type", "severity",
                "status", "mttd_seconds", "resolved_at",
            ] if c in df.columns
        ]
        st.dataframe(df[display_cols].tail(20), use_container_width=True)
    else:
        st.caption("No incidents recorded yet.")


# ── main ─────────────────────────────────────────────────────────────────

st.title("⚡ Incident Response Dashboard")
st.caption("Auto-refreshes every 5 seconds")

live_dashboard()
