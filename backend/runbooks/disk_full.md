# Runbook: Disk Space Exhaustion (`disk_full.md`)

## Incident Description
Critical disk space exhaustion (90% or above) on filesystem `/dev/sda1` attached to `storage-service`, leaving minimal free capacity (e.g., 2 GB available) and risking write failures or service crashes.

## Symptoms
- Disk utilization crosses warning (80%) and critical (90%+) thresholds (e.g., 96%).
- Available free space drops to critically low levels (e.g., 2 GB on `/dev/sda1`).
- Logs contain `DISK_SPACE_CRITICAL` and `Temporary storage threshold exceeded` referencing `/var/tmp/sim-cache`.
- `storage-service` enters `DEGRADED` state.

## Possible Causes
- Accumulation of stale temporary cache or spool files in `/var/tmp/sim-cache`.
- Unrotated temporary diagnostic dumps or orphaned upload buffers.

## Diagnostic Procedures
1. Check disk utilization percentage and available GB on `/dev/sda1` via `get_system_metrics()`.
2. Inspect `storage-service` logs for `DISK_SPACE_CRITICAL` and temporary storage warnings.
3. Confirm temporary cache footprint (`temp_files_gb`) before proposing cleanup.

## Recommended Remediation
- **Primary Safe Action (Allowlisted):** `cleanup_simulated_temp_files` targeting only simulated temporary cache state (`/var/tmp/sim-cache`), reclaiming disk space safely.
- Risk classification: `LOW` risk (controlled simulated temporary cache cleanup; non-destructive to persistent user data).
- Never delete actual host user files or run unvalidated filesystem deletion commands.

## Validation Procedures
1. Re-run `get_system_metrics()` after cleanup completes.
2. Verify disk utilization drops below 80% (target healthy range: ~50%–55%) and available space increases significantly.
3. Confirm `storage-service` health returns to `HEALTHY` via `check_service_health("storage-service")`.

## Rollback Instructions
- If simulated cleanup fails or disk utilization remains critical (>= 90%), restore prior simulated cache metadata snapshot, abort further automated cleanup, and escalate to Storage Operations for volume expansion.

## Safety Considerations
- Cleanup MUST operate exclusively on simulated temporary storage metadata.
- Never target root directories, database data directories, or real host user files.
