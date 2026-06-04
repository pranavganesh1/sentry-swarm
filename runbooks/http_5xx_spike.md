# Runbook: HTTP 5xx Error Spike

## Incident Type
http_5xx

## Description
A sudden increase in HTTP 500/503 responses from one or more services. Usually caused by
an unhandled exception, a bad deploy, or an upstream dependency failing.

## Detection Signals
- ERROR rate exceeds 10% of total requests in a 30-second window
- Repeated "500 Internal Server Error" or "503 Service Unavailable" in nginx/app logs
- "Unhandled exception" appearing across multiple log lines

## Triage Steps
1. Identify which service is emitting the 5xx errors by checking the service field in logs.
2. Check whether the spike started after a recent deployment.
3. Look for a specific exception class repeating, such as NullPointerException or ValueError.
4. Check whether the error is isolated to one endpoint or affecting all routes.

## Remediation Steps
### If caused by a bad deploy:
```
kubectl rollout undo deployment/<service-name>
kubectl rollout status deployment/<service-name>
```

### If caused by an unhandled exception in code:
- Identify the exception from the stack trace.
- Check recent commits for the affected file.
- Hotfix or revert the offending commit.

### If upstream dependency is down:
- Check the dependency's health endpoint.
- Enable circuit breaker if available.
- Return graceful degraded response until dependency recovers.

### Restart the service if exception is transient:
```
systemctl restart <service-name>
# or in kubernetes:
kubectl rollout restart deployment/<service-name>
```

## Escalation
If error rate stays above 20% for more than 5 minutes, page the on-call engineer.

## Post-Mortem Tags
bad-deploy, unhandled-exception, upstream-failure
