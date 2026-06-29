# ⚡ Sentry-Swarm — Multi-Agent DevOps Incident Response

An AI-powered, multi-agent system that **automatically detects, diagnoses, and responds** to production incidents in real-time. The system monitors application logs, classifies incidents using LLM-based analysis, and generates both fix plans and stakeholder communications — reducing mean-time-to-diagnosis (MTTD) by **~68%** compared to manual triage.

---

## Architecture

```
logs/app.log → Watcher → SQLite Buffer → Sentry Agent → Classifier (Gemini)
                                              ↓
                                     Orchestrator Pipeline
                                    ┌──────────────────────┐
                                    │  1. Diagnostician     │  ← Runbook lookup
                                    │  2. Fix-Planner       │  ← Remediation steps
                                    │  3. Comms Agent       │  ← Slack + Post-mortem
                                    └──────────────────────┘
                                              ↓
                                  Rich TUI / Streamlit Dashboard
```

### Agents

| Agent | Role |
|-------|------|
| **Sentry** | Monitors error rates, triggers LLM classifier when thresholds are breached |
| **Classifier** | Gemini 2.0 Flash — classifies incident type, severity, and affected services |
| **Diagnostician** | Correlates trigger events with runbooks to build a diagnosis |
| **Fix-Planner** | Extracts remediation steps from runbooks, builds a structured fix plan |
| **Comms** | Generates a Slack update and blameless post-mortem via LLM |

### Incident Types

`http_5xx` · `db_timeout` · `oom_kill` · `failed_deploy` · `cascading_failure`

---

## Quick Start

### 1. Setup

```bash
python -m venv venv
venv\Scripts\activate        # Windows
# source venv/bin/activate   # Linux/Mac

pip install -r requirements.txt
```

### 2. Configure

```bash
cp .env.example .env
# Edit .env and add your GOOGLE_API_KEY
```

### 3. Run

**Terminal 1** — Start the log watcher:
```bash
python ingestion/watcher.py
```

**Terminal 2** — Start the log generator:
```bash
python log_generator.py
```

**Terminal 3** — Start the main system with Rich dashboard:
```bash
python main.py
```

**Optional** — Streamlit web dashboard:
```bash
streamlit run dashboard_streamlit.py
```

---

## Project Structure

```
├── main.py                  # Entry point — starts orchestrator + Rich dashboard
├── orchestrator.py          # Central pipeline coordinator (threads, watchdog, commands)
├── state.py                 # IncidentState dataclass
├── metrics.py               # MTTD tracking and metrics aggregation
├── commands.py              # File-based cross-process command queue
│
├── agents/
│   ├── sentry.py            # Log monitor + incident trigger
│   ├── classifier.py        # LLM-based log classification (Gemini)
│   ├── diagnostician.py     # Diagnosis builder with runbook lookup
│   ├── fix_planner.py       # Remediation step extractor
│   └── comms.py             # Slack update + post-mortem generation
│
├── ingestion/
│   ├── watcher.py           # File watcher (watchdog) → SQLite
│   ├── parser.py            # Log line parser with incident type detection
│   └── buffer.py            # SQLite event buffer with error rate queries
│
├── sensors/
│   ├── sensor_interface.py  # Physical sensor (UNO Q) integration
│   └── __init__.py
│
├── runbooks/                # 5 incident response runbooks
├── dashboard_rich.py        # Rich TUI live dashboard
├── dashboard_streamlit.py   # Streamlit web dashboard
├── log_generator.py         # Normal traffic + periodic spike simulator
├── log_generator_stress.py  # Concurrent multi-type stress testing
├── mobile_app/              # SSE-based mobile responder UI
│
├── benchmark/
│   ├── run_benchmark.py     # Formal 5-type MTTD benchmark
│   └── manual_baseline.md   # Manual triage baseline methodology
│
├── test_*.py                # Pytest unit tests
├── requirements.txt
└── .github/workflows/ci.yml # GitHub Actions CI
```

---

## Testing

```bash
python -m pytest -v
```

## Benchmarking

```bash
python benchmark/run_benchmark.py            # Run full 5-type benchmark
python benchmark/run_benchmark.py --summary  # Reprint last results
```

---

## Key Design Decisions

- **Fallback chains**: Every LLM-dependent agent has a deterministic fallback path, ensuring the pipeline never crashes due to API failures
- **Concurrent pipeline**: Up to 3 incidents processed simultaneously via semaphore-controlled worker threads
- **Watchdog**: Force-closes stuck incidents after 180s to prevent pipeline deadlocks
- **Cooldown system**: Prevents duplicate incident firing with per-type cooldowns + severity escalation override
- **File-based IPC**: Streamlit dashboard communicates with the orchestrator via a JSON command queue — no shared memory needed

---

## License

MIT
