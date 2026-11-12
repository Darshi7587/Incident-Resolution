# Runbook: Application Service Failure (`service_failure.md`)

## Incident Description
Critical outage of `payment-api` (`FAILED` status, HTTP 503) caused by refused connections or unreachable downstream database server `db-server`.

## Symptoms
- `payment-api` health check reports `FAILED`.
- `db-server` connectivity check returns `db_connected=False` (`UNREACHABLE`).
- Logs show `payment-api unavailable (HTTP 503)`, `Connection refused while connecting to db-server:5432`, `Database connection failed`, and `CRITICAL SERVICE_FAILURE`.

## Possible Causes
- Downstream `db-server` process stopped or connection listener unreachable.
- Exhausted or broken database connection pool in `payment-api` requiring coordinated service restoration.

## Diagnostic Procedures
1. Check `payment-api` and `db-server` statuses via `get_system_metrics()` and `check_service_health("payment-api")`.
2. Correlate `Connection refused` and `Database connection failed` events in logs.
3. Confirm `db_connected` state before restoring dependent application services.

## Recommended Remediation
- **Primary Safe Action (Allowlisted):** `restore_simulated_service` to restore `db-server` connectivity and restart `payment-api` in dependency order.
- Risk classification: `HIGH` risk because restoring and restarting `payment-api` and `db-server` affects critical payment transaction paths.
- Explicit human approval is mandatory before execution.

## Validation Procedures
1. Run `check_service_health("payment-api")` and `get_system_metrics()`.
2. Verify `db_connected == True`, `db-server == HEALTHY`, and `payment-api == HEALTHY`.
3. Only mark the incident `RESOLVED` once both database connectivity and API health pass verification.

## Rollback Instructions
- If `payment-api` or `db-server` fails post-remediation health verification, invoke `rollback_simulated_action` to revert service state, record failure evidence, and escalate immediately to On-Call Payment Platform & DBA teams.

## Safety Considerations
- Disruptive restarts on payment infrastructure MUST pause for explicit human operator approval.
- Rejections must halt execution immediately and trigger escalation or alternative planning.
