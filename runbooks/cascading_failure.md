# Runbook: Cascading Service Failure

## Incident Type
cascading_failure

## Description
Multiple services are failing simultaneously, often because one critical dependency such
as auth, database, or a message queue went down and upstream services could not handle the
failure gracefully. Errors spread across services rapidly.

## Detection Signals
- ERROR or FATAL logs appearing in 3 or more services within a 60-second window
- "connection refused" or "upstream unavailable" appearing across different services
- Auth or database service is the common upstream in all error chains
- Error rates rise in dependent services after the first root-service failure

## Triage Steps
1. Identify the root service by finding which service's errors appeared first.
2. Check if auth-service or db-proxy is involved, since they are common cascade sources.
3. Map the dependency chain and note which services depend on the failing one.
4. Check if circuit breakers are open or retry storms are amplifying the failure.
5. Separate symptoms from the root cause before restarting multiple services.

## Remediation Steps
### Fix the root service first:
- Use db_timeout.md if the database is the root cause.
- Use oom_kill.md if a core service was OOM killed.
- Use failed_deploy.md if a bad deploy triggered the cascade.

### Force-restart dependent services after root is fixed:
```
kubectl rollout restart deployment/auth-service
kubectl rollout restart deployment/user-api
kubectl rollout restart deployment/payment-service
```

### If cascade persists after root fix:
- Check for stuck connection pools in each service because they may not auto-recover.
- Restart services in dependency order: root first, then immediate dependents, then leaves.
- Reduce retry volume or enable backoff if clients are overwhelming the recovered service.

### Enable maintenance mode if unresolved in under 10 minutes:
- Route all traffic to a maintenance page via nginx config.
- Preserve core infrastructure while user-facing failures are still compounding.
- Continue root cause work with the public traffic path quieted.

## Escalation
Cascading failures that span 3 or more services for more than 10 minutes require all-hands.
Page the on-call lead and open a war room.

## Post-Mortem Tags
cascading-failure, dependency-chain, circuit-breaker, war-room
