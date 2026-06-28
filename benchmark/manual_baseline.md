# Manual Debugging Baseline (estimated)

For each incident type, the baseline represents the time a human on-call
engineer would need to **notice** and **diagnose** the problem, starting cold
(paged, no prior context, no AI assistance).

## Methodology

Each step below represents a sequential action an on-call engineer performs
from the moment their pager fires.  Times are conservative estimates derived
from industry SRE surveys and the authors' on-call experience.

| Step                                     | Typical time |
|------------------------------------------|--------------|
| Alert fires → engineer acknowledges      | 60–120s      |
| Open dashboards / log viewer             | 30–60s       |
| Search/filter logs for the error pattern | 60–180s      |
| Correlate across services manually       | 60–300s      |
| Identify root cause + check runbook      | 60–180s      |
| **Total (low end)**                      | **270s (4.5 min)** |
| **Total (high end)**                     | **840s (14 min)**  |

## Per-Incident-Type Baselines

We use the midpoint of low/high per incident type, weighted by complexity:

| Incident Type      | Complexity  | Estimated Manual Baseline | Reasoning |
|--------------------|-------------|---------------------------|-----------|
| `http_5xx`         | Low         | **300s (5 min)**          | Single-service pattern, obvious 500/503 errors in access logs. Quick to grep but still requires dashboard correlation. |
| `db_timeout`       | Medium      | **480s (8 min)**          | Cross-service correlation needed — db-proxy timeout cascades to upstream consumers. Must check connection pool metrics and query logs. |
| `oom_kill`         | Medium      | **420s (7 min)**          | Requires memory trend analysis; OOM kill messages are clear but identifying the memory leak source takes investigation. |
| `failed_deploy`    | Low         | **240s (4 min)**          | Usually fast to spot — deployment pipeline status is typically visible. CrashLoopBackOff appears in pod status. |
| `cascading_failure`| High        | **780s (13 min)**         | Hardest pattern — multiple services failing simultaneously. Must trace the dependency chain to find the root service. Noise from multiple failure points slows diagnosis. |

**Weighted average:** ~444s (~7.4 min)

## What "MTTD" Measures in This Benchmark

> **MTTD = time from first error log line → completed diagnosis (root cause
> identified + runbook matched + fix plan generated).**

The AI system has an inherent advantage over human baselines because it:
1. Has zero "paging lag" — it's always watching
2. Correlates logs computationally instead of visually scanning
3. Retrieves runbooks programmatically via RAG

This is an honest, structural advantage of automated systems — not an artifact
of unfair benchmarking.  The manual baseline includes acknowledgment delay
because that's genuinely part of MTTD in real operations.

## How to Use This Number

**Defensible framing for resume / interview:**

> "MTTD" here = time from first error log to completed diagnosis. The AI system
> detects and diagnoses in ~10s on average vs an estimated 4–13 minutes for a
> human starting cold, primarily because automated log correlation eliminates
> manual searching and cross-referencing.

**Don't say:** "97% faster" without context.
**Do say:** "~10s average diagnosis time vs 4–13 minute manual baseline, validated
via automated benchmark across 5 incident types."
