# Runbook: Out of Memory (OOM) Kill

## Incident Type
oom_kill

## Description
A service process has been killed by the operating system OOM killer after exceeding its
memory limit. The service becomes unavailable until restarted. Common causes include a
memory leak, large payload processing, or insufficient memory limits configured.

## Detection Signals
- "OutOfMemoryError" or "OOM killer" in service logs
- "Process killed" with high RSS memory value
- Service becomes unreachable, such as nginx logging "connection refused" for that upstream
- Memory usage warning logged before the kill, usually above 85% usage

## Triage Steps
1. Confirm which service was OOM killed.
2. Check whether memory usage grew gradually, suggesting a leak, or jumped suddenly from a payload.
3. Check if this is a recurring incident or a one-time failure.
4. Check current memory limits set for the pod or process.
5. Compare recent deploys against the first high-memory warning.

## Remediation Steps
### Immediate restart:
```
kubectl rollout restart deployment/<service-name>
kubectl get pods -l app=<service-name> -w
```

### Increase memory limit temporarily:
Edit the deployment and raise the memory limit:
```
kubectl edit deployment <service-name>
# under resources.limits.memory, increase to next tier, such as 512Mi to 1Gi
```

### If memory leak is suspected:
- Enable heap dump on next OOM with `-XX:+HeapDumpOnOutOfMemoryError` for JVM services.
- Monitor memory over 10 minutes after restart.
- If it climbs steadily, treat it as a leak.
- Identify the leaking object from the heap dump.
- Schedule a fix and set an alert at 80% memory usage.

### Horizontal scale as temporary relief:
```
kubectl scale deployment <service-name> --replicas=3
```

## Escalation
If the service cannot stay up for more than 5 minutes after restart, page the service owner.

## Post-Mortem Tags
memory-leak, oom, resource-limits, jvm
