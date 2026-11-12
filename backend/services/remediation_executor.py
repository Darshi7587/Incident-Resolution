"""Controlled execution of predefined, isolated simulated remediation actions."""

from __future__ import annotations

import json
from copy import deepcopy
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from sqlalchemy.orm import Session

from backend.database.models import AgentExecution, AuditLog, RemediationAction
from backend.services.incident_simulator import SimulatedInfrastructure
from backend.services.risk_engine import ALLOWLISTED_ACTIONS


class UnsafeActionError(PermissionError):
    """Raised when attempting to execute an unapproved or non-allowlisted action."""


class RemediationExecutor:
    """Executes allowlisted simulated remediation actions and supports controlled rollback."""

    def __init__(self, infra: Optional[SimulatedInfrastructure] = None) -> None:
        self.infra = infra or SimulatedInfrastructure()

    def restart_simulated_service(
        self,
        service_name: str,
        simulate_failure: bool = False,
    ) -> Dict[str, Any]:
        """Restart a simulated service (e.g., application-server) inside SimulatedInfrastructure."""
        before = deepcopy(self.infra.get_system_metrics())
        if simulate_failure:
            after = self.infra.update_state(
                {
                    "cpu_usage": 93.0,
                    "services": {service_name: "FAILED"},
                    "cpu_history": [*before.get("cpu_history", [])[-2:], 93.0],
                }
            )
            return {
                "executed": True,
                "action_succeeded": False,
                "before_state": before,
                "after_state": after,
                "message": f"Simulated failure: '{service_name}' restart did not recover CPU (93.0%) and service entered FAILED state.",
            }

        after = self.infra.update_state(
            {
                "cpu_usage": 26.0,
                "services": {service_name: "HEALTHY"},
                "cpu_history": [*before.get("cpu_history", [])[-2:], 26.0],
            }
        )
        return {
            "executed": True,
            "action_succeeded": True,
            "before_state": before,
            "after_state": after,
            "message": f"Simulated service '{service_name}' restarted cleanly; CPU dropped from {before.get('cpu_usage')}% to 26.0%.",
        }

    def cleanup_simulated_temp_files(
        self,
        service_name: str = "storage-service",
        simulate_failure: bool = False,
    ) -> Dict[str, Any]:
        """Clean simulated temporary cache metadata without touching real host files."""
        before = deepcopy(self.infra.get_system_metrics())
        if simulate_failure:
            after = self.infra.update_state(
                {
                    "disk_usage": 94.0,
                    "disk_available_gb": 6.0,
                    "services": {service_name: "DEGRADED"},
                }
            )
            return {
                "executed": True,
                "action_succeeded": False,
                "before_state": before,
                "after_state": after,
                "message": "Simulated failure: temporary cache cleanup reclaimed insufficient space (disk still at 94.0%).",
            }

        after = self.infra.update_state(
            {
                "disk_usage": 54.0,
                "disk_available_gb": 46.0,
                "temp_files_gb": 0.5,
                "services": {service_name: "HEALTHY"},
            }
        )
        return {
            "executed": True,
            "action_succeeded": True,
            "before_state": before,
            "after_state": after,
            "message": f"Cleaned simulated temporary files in /var/tmp/sim-cache; disk usage reduced from {before.get('disk_usage')}% to 54.0% (46.0 GB free).",
        }

    def restore_simulated_service(
        self,
        service_name: str = "payment-api",
        simulate_failure: bool = False,
    ) -> Dict[str, Any]:
        """Restore simulated database connectivity and dependent application service."""
        before = deepcopy(self.infra.get_system_metrics())
        if simulate_failure:
            after = self.infra.update_state(
                {
                    "db_server_status": "UNREACHABLE",
                    "db_connected": False,
                    "services": {service_name: "FAILED", "db-server": "UNREACHABLE"},
                }
            )
            return {
                "executed": True,
                "action_succeeded": False,
                "before_state": before,
                "after_state": after,
                "message": "Simulated failure: db-server remained unreachable after restore attempt; payment-api still FAILED.",
            }

        after = self.infra.update_state(
            {
                "db_server_status": "HEALTHY",
                "db_connected": True,
                "services": {service_name: "HEALTHY", "db-server": "HEALTHY"},
            }
        )
        return {
            "executed": True,
            "action_succeeded": True,
            "before_state": before,
            "after_state": after,
            "message": "Restored db-server connectivity and restarted payment-api; both services are HEALTHY.",
        }

    def rollback_simulated_action(
        self,
        before_state: Dict[str, Any],
        action_id: Optional[str] = None,
        incident_id: Optional[str] = None,
        db: Optional[Session] = None,
    ) -> Dict[str, Any]:
        """Revert simulated infrastructure back to pre-remediation snapshot."""
        if not before_state:
            return {"rolled_back": False, "message": "No before_state snapshot available for rollback."}

        restored_fields = {
            k: before_state[k]
            for k in (
                "cpu_usage",
                "memory_usage",
                "disk_usage",
                "disk_available_gb",
                "temp_files_gb",
                "db_server_status",
                "db_connected",
                "services",
                "cpu_history",
            )
            if k in before_state
        }
        restored = self.infra.update_state(restored_fields)

        if db is not None and action_id is not None:
            action_row = db.query(RemediationAction).filter(RemediationAction.id == action_id).first()
            if action_row is not None:
                action_row.execution_status = "ROLLED_BACK"
                action_row.rollback_info_json = json.dumps(
                    {
                        "rolled_back": True,
                        "rolled_back_at": datetime.now(timezone.utc).isoformat(),
                        "restored_state": restored,
                    }
                )
            if incident_id is not None:
                db.add(
                    AuditLog(
                        incident_id=incident_id,
                        actor="RemediationExecutor",
                        event_type="REMEDIATION_ROLLED_BACK",
                        what_happened=f"Rolled back simulated action {action_id} to pre-remediation snapshot.",
                        action_executed=action_row.action_name if action_row else None,
                        rollback_required=True,
                        resolved=False,
                    )
                )
            db.commit()

        return {
            "rolled_back": True,
            "restored_state": restored,
            "message": "Simulated infrastructure state successfully rolled back to pre-remediation snapshot.",
        }

    def execute_action(
        self,
        action_name: str,
        target_service: str,
        approval_status: str,
        simulate_failure: bool = False,
        action_id: Optional[str] = None,
        incident_id: Optional[str] = None,
        db: Optional[Session] = None,
    ) -> Dict[str, Any]:
        """Execute an allowlisted simulated action strictly after verifying approval status."""
        if action_name not in ALLOWLISTED_ACTIONS:
            raise UnsafeActionError(f"Action '{action_name}' is not in the approved allowlist.")

        if approval_status not in {"APPROVED", "AUTO_APPROVED"}:
            raise UnsafeActionError(
                f"Refusing to execute '{action_name}' because approval_status='{approval_status}'."
            )

        if action_name == "cleanup_simulated_temp_files":
            exec_res = self.cleanup_simulated_temp_files(service_name=target_service, simulate_failure=simulate_failure)
        elif action_name == "restart_simulated_service":
            exec_res = self.restart_simulated_service(service_name=target_service, simulate_failure=simulate_failure)
        elif action_name == "restore_simulated_service":
            exec_res = self.restore_simulated_service(service_name=target_service, simulate_failure=simulate_failure)
        else:
            raise UnsafeActionError(f"No executor bound for allowlisted action '{action_name}'.")

        now = datetime.now(timezone.utc)
        exec_status = "EXECUTED" if exec_res["action_succeeded"] else "EXECUTION_FAILED"
        rollback_info = {
            "rollback_action": ALLOWLISTED_ACTIONS[action_name].rollback_action,
            "can_rollback": True,
            "before_state_captured": True,
        }

        if db is not None and action_id is not None:
            action_row = db.query(RemediationAction).filter(RemediationAction.id == action_id).first()
            if action_row is not None:
                action_row.approval_status = approval_status
                action_row.execution_status = exec_status
                action_row.before_state_json = json.dumps(exec_res["before_state"])
                action_row.after_state_json = json.dumps(exec_res["after_state"])
                action_row.rollback_info_json = json.dumps(rollback_info)
                action_row.executed_at = now

            if incident_id is not None:
                db.add(
                    AgentExecution(
                        incident_id=incident_id,
                        agent_name="Remediation Executor",
                        status=exec_status,
                        message=exec_res["message"],
                        input_summary=json.dumps({"action_name": action_name, "target_service": target_service}),
                        output_summary=json.dumps({"action_succeeded": exec_res["action_succeeded"]}),
                    )
                )
                db.add(
                    AuditLog(
                        incident_id=incident_id,
                        actor="Remediation Executor",
                        event_type="REMEDIATION_EXECUTED",
                        what_happened=exec_res["message"],
                        proposed_action=action_name,
                        approval_required=(approval_status == "APPROVED"),
                        action_executed=action_name,
                        rollback_required=not exec_res["action_succeeded"],
                    )
                )
            db.commit()

        return {
            "action_id": action_id,
            "action_name": action_name,
            "target_service": target_service,
            "approval_status": approval_status,
            "execution_status": exec_status,
            "action_succeeded": exec_res["action_succeeded"],
            "before_state": exec_res["before_state"],
            "after_state": exec_res["after_state"],
            "rollback_info": rollback_info,
            "message": exec_res["message"],
            "executed_at": now.isoformat(),
        }
