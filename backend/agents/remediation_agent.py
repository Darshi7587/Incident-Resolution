"""Agent 6: Remediation Planning Agent — plans safe allowlisted actions and creates approvals."""

from __future__ import annotations

import json
import uuid
from typing import Any, Dict, Optional

from sqlalchemy.orm import Session

from backend.config import Settings, get_settings
from backend.database.models import AgentExecution, ApprovalRequest, AuditLog, RemediationAction
from backend.services.risk_engine import RiskEngine


class RemediationPlanningAgent:
    """Selects an allowlisted remediation action from RCA + runbook evidence and evaluates risk."""

    name = "Remediation Planning Agent"

    def __init__(self, settings: Optional[Settings] = None) -> None:
        self.settings = settings or get_settings()
        self.risk_engine = RiskEngine(settings=self.settings)

    def _select_action(
        self,
        incident_type: str,
        affected_service: str,
        rca_result: Dict[str, Any],
        rag_result: Dict[str, Any],
    ) -> Dict[str, str]:
        primary_runbook = (rag_result.get("primary_runbook") or "").lower()
        cause = (rca_result.get("probable_cause") or "").lower()

        if incident_type == "disk_full" or "disk_full" in primary_runbook or "temporary file" in cause or "disk" in cause:
            return {
                "action_name": "cleanup_simulated_temp_files",
                "target_service": "storage-service",
                "rationale": (
                    "Selected 'cleanup_simulated_temp_files' per disk_full.md runbook because "
                    "disk exhaustion is linked to temporary cache accumulation in /var/tmp/sim-cache."
                ),
                "expected_outcome": "Disk utilization drops below 80% warning threshold and storage-service returns to HEALTHY.",
            }

        if incident_type == "service_failure" or "service_failure" in primary_runbook or "database" in cause or "payment-api" in affected_service:
            return {
                "action_name": "restore_simulated_service",
                "target_service": "payment-api",
                "rationale": (
                    "Selected 'restore_simulated_service' per service_failure.md runbook to restore "
                    "db-server connectivity and restart payment-api cleanly in dependency order."
                ),
                "expected_outcome": "db-server connectivity is restored (db_connected=True) and payment-api returns to HEALTHY.",
            }

        # Default for high_cpu or cpu_high.md
        return {
            "action_name": "restart_simulated_service",
            "target_service": affected_service or "application-server",
            "rationale": (
                "Selected 'restart_simulated_service' per cpu_high.md runbook to terminate "
                "runaway worker threads exhausting CPU on application-server."
            ),
            "expected_outcome": "CPU utilization drops below 70% threshold and application-server returns to HEALTHY.",
        }

    def plan(
        self,
        incident_id: str,
        incident_type: str,
        affected_service: str,
        rca_result: Dict[str, Any],
        rag_result: Dict[str, Any],
        before_metrics: Optional[Dict[str, Any]] = None,
        db: Optional[Session] = None,
    ) -> Dict[str, Any]:
        """Create a validated remediation plan, run RiskEngine, and persist pending approval if needed."""
        selection = self._select_action(incident_type, affected_service, rca_result, rag_result)
        risk_eval = self.risk_engine.evaluate(
            action_name=selection["action_name"],
            target_service=selection["target_service"],
        )

        action_id = f"ACT-{uuid.uuid4().hex[:10].upper()}"
        approval_id = f"APR-{uuid.uuid4().hex[:10].upper()}" if risk_eval["requires_approval"] else None
        approval_status = "PENDING" if risk_eval["requires_approval"] else "AUTO_APPROVED"

        plan = {
            "agent": self.name,
            "status": "COMPLETED",
            "action_id": action_id,
            "approval_id": approval_id,
            "action_name": selection["action_name"],
            "action_description": risk_eval.get("description", ""),
            "target_service": selection["target_service"],
            "rationale": selection["rationale"],
            "expected_outcome": selection["expected_outcome"],
            "risk_level": risk_eval["risk_level"],
            "requires_approval": risk_eval["requires_approval"],
            "approval_status": approval_status,
            "policy_reason": risk_eval["policy_reason"],
            "rollback_action": risk_eval.get("rollback_action", ""),
        }

        if db is not None:
            db.add(
                RemediationAction(
                    id=action_id,
                    incident_id=incident_id,
                    action_name=plan["action_name"],
                    action_description=plan["action_description"],
                    rationale=plan["rationale"],
                    expected_outcome=plan["expected_outcome"],
                    risk_level=str(plan["risk_level"]),
                    approval_status=approval_status,
                    execution_status="PENDING",
                    before_state_json=json.dumps(before_metrics or {}),
                    after_state_json="{}",
                    rollback_info_json=json.dumps({"rollback_action": plan["rollback_action"]}),
                )
            )

            if risk_eval["requires_approval"] and approval_id is not None:
                db.add(
                    ApprovalRequest(
                        id=approval_id,
                        incident_id=incident_id,
                        action_id=action_id,
                        proposed_action=plan["action_name"],
                        reason=plan["rationale"],
                        risk_level=str(plan["risk_level"]),
                        expected_outcome=plan["expected_outcome"],
                        status="PENDING",
                    )
                )

            db.add(
                AgentExecution(
                    incident_id=incident_id,
                    agent_name=self.name,
                    status="COMPLETED",
                    message=(
                        f"Proposed {plan['action_name']} (risk={plan['risk_level']}, "
                        f"requires_approval={plan['requires_approval']})"
                    ),
                    input_summary=json.dumps({"primary_runbook": rag_result.get("primary_runbook")}),
                    output_summary=json.dumps(
                        {
                            "action_id": action_id,
                            "action_name": plan["action_name"],
                            "risk_level": plan["risk_level"],
                            "requires_approval": plan["requires_approval"],
                        }
                    ),
                )
            )
            db.add(
                AgentExecution(
                    incident_id=incident_id,
                    agent_name="Risk Engine",
                    status="APPROVAL_REQUIRED" if plan["requires_approval"] else "AUTO_APPROVED",
                    message=str(plan["policy_reason"]),
                    input_summary=json.dumps({"action_name": plan["action_name"], "risk_level": plan["risk_level"]}),
                    output_summary=json.dumps({"requires_approval": plan["requires_approval"], "approval_id": approval_id}),
                )
            )
            db.add(
                AuditLog(
                    incident_id=incident_id,
                    actor=self.name,
                    event_type="REMEDIATION_PLANNED",
                    what_happened=f"Proposed {plan['action_name']} ({plan['risk_level']} risk). {plan['policy_reason']}",
                    proposed_action=plan["action_name"],
                    approval_required=bool(plan["requires_approval"]),
                )
            )
            db.commit()

        return plan
