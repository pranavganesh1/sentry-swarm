# Runbook: Database Connection Timeout

## Incident Type
db_timeout

## Description
Database queries are timing out or the connection pool is exhausted. This causes upstream
services to fail when trying to read or write data. Often caused by a slow query, a missing
index, or a traffic spike overwhelming the database.

## Detection Signals
- "Connection timeout" in db-proxy logs
- "Query exceeded max execution time" in logs
- "Connection pool exhausted" with pool size at or near max
- Upstream services logging "upstream db-proxy timeout"

## Triage Steps
1. Check if this is a single slow query or all queries timing out.
2. Check current database connection count against max_connections.
3. Look for any long-running queries blocking others.
4. Check database CPU and memory metrics.
5. Check if a recent schema change or new query was deployed.

## Remediation Steps
### Kill long-running queries (PostgreSQL):
```sql
SELECT pid, now() - pg_stat_activity.query_start AS duration, query
FROM pg_stat_activity
WHERE state = 'active' AND now() - pg_stat_activity.query_start > interval '30 seconds';

SELECT pg_terminate_backend(pid) FROM pg_stat_activity
WHERE now() - query_start > interval '30 seconds' AND state = 'active';
```

### Scale up connection pool:
- Increase max pool size in db-proxy config and restart.
- Add a read replica and route read traffic there if the primary is saturated.

### If traffic spike is the cause:
```
kubectl scale deployment db-proxy --replicas=3
```

### Restart db-proxy if pool is stuck:
```
kubectl rollout restart deployment/db-proxy
```

## Escalation
If all queries are timing out and kill commands do not help, escalate to the DBA team.

## Post-Mortem Tags
slow-query, connection-pool, missing-index, traffic-spike
