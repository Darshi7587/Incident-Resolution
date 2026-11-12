# Runbook: High CPU Utilization (`cpu_high.md`)

## Incident Description
Sustained high CPU utilization (above 90% critical threshold) on `application-server` causing thread pool saturation, elevated request latency, and potential service unresponsiveness.

## Symptoms
- CPU utilization rises above warning (70%) and critical (90%) thresholds (e.g., 45% -> 72% -> 95%).
- Log entries containing `CPU_THRESHOLD_EXCEEDED` and `resource exhaustion detected`.
- `application-server` status transitions from `HEALTHY` to `DEGRADED`.
- Memory and disk utilization typically remain within normal limits.

## Possible Causes
- Runaway worker thread pool or infinite compute loop inside `application-server`.
- Sudden spike in unthrottled background batch jobs.
- Deadlocked or spinning worker threads consuming CPU cores without yielding.

## Diagnostic Procedures
1. Verify CPU trend history (e.g., 45% -> 72% -> 95%) via `get_system_metrics()`.
2. Inspect `application-server` logs for `CPU_THRESHOLD_EXCEEDED`, `resource exhaustion`, or thread pool errors.
3. Confirm whether memory and disk remain within normal operating thresholds to isolate compute saturation.

## Recommended Remediation
- **Primary Safe Action (Allowlisted):** `restart_simulated_service` for `application-server` to terminate runaway worker threads and restore clean thread pool allocation.
- Classify as `MEDIUM` or `HIGH` risk depending on policy; require human approval when configured before restarting active application services.
- Never execute arbitrary shell commands or `kill -9` commands generated dynamically by an LLM.

## Validation Procedures
1. Wait for simulated service restart stabilization.
2. Call `get_system_metrics()` and `check_service_health("application-server")`.
3. Verify CPU utilization drops below 70% (target healthy range: 20%–35%) and `application-server` status returns to `HEALTHY`.
4. Only mark incident `RESOLVED` after post-remediation metrics confirm recovery.

## Rollback Instructions
- If CPU remains above threshold or `application-server` enters `FAILED` state after restart, restore the prior simulated service snapshot (`rollback_simulated_action`), mark remediation as failed, and escalate to Tier-2 Infrastructure Engineering.

## Safety Considerations
- Restarting `application-server` interrupts in-flight simulated transactions.
- Ensure human approval is enforced when `require_approval_medium_risk` or `require_approval_high_risk` is enabled.
- All actions must remain strictly isolated to the simulated infrastructure state.
