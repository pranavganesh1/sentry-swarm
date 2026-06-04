# Runbook: Failed Deployment

## Incident Type
failed_deploy

## Description
A deployment did not complete successfully. Pods may be crash-looping, stuck in Pending,
or the rollout may have timed out. Usually caused by a bad image, misconfigured
environment variables, missing secrets, or a failing health check.

## Detection Signals
- Exit code 1 in deploy pipeline logs
- Pods in CrashLoopBackOff or ImagePullBackOff state
- Rollout stuck with 0 ready replicas
- Health check endpoint returning non-200 after deploy

## Triage Steps
1. Check pod status immediately after deploy.
2. Check pod logs for the crash reason.
3. Check if the container image exists and was pushed correctly.
4. Check if environment variables or secrets changed.
5. Check readiness and liveness probe configuration for the deployed service.

## Remediation Steps
### Rollback immediately:
```
kubectl rollout undo deployment/<service-name>
kubectl rollout status deployment/<service-name>
```

### Check pod logs for crash reason:
```
kubectl logs deployment/<service-name> --previous
kubectl describe pod <pod-name>
```

### If ImagePullBackOff:
- Verify the image tag was pushed to the registry.
- Check that registry credentials and image pull secrets are valid.
- Confirm the deployment references the intended image repository.

### If CrashLoopBackOff:
- Check the exit code; exit 1 usually means app error and exit 137 usually means OOM.
- Run the container locally with the same environment variables to reproduce.
- Verify required config files, secrets, and service accounts are mounted.

### If health checks are failing:
- Confirm the health endpoint path and port.
- Increase startup probe delay if the app starts slowly after deploy.
- Check whether the app is bound to the expected interface.

## Escalation
If rollback also fails, escalate to the platform team immediately.

## Post-Mortem Tags
bad-image, crashloop, health-check, env-config
