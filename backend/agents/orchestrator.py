"""Agent 1: Orchestrator Agent — coordinates multi-agent execution, pause/resume, and escalation."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from sqlalchemy.orm import Session

from backend.config import Settings, get_settings
from backend.database.models import AgentExecution, ApprovalRequest, AuditLog, Incident, RemediationAction
from backend.services.incident_simulator import SimulatedInfrastructure
from backend.workflows.incident_workflow import IncidentState, build_incident_graph, build_resume_graph


class OrchestratorAgent:
    """Coordinates specialized agents using LangGraph and tracks persistent workflow state."""

    name = "Orchestrator Agent"

    def __init__(
        self,
        settings: Optional[Settings] = None,
        infra: Optional[SimulatedInfrastructure] = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.infra = infra or SimulatedInfrastructure()

    def process_incident(
        self,
        db: Session,
        incident_id: str,
        rag_min_relevance: float = 0.25,
    ) -> Dict[str, Any]:
        """Load incident from SQLite, run LangGraph workflow, and persist state updates."""
        incident = db.query(Incident).filter(Incident.id == incident_id).first()
        if incident is None:
            raise ValueError(f"Incident '{incident_id}' not found")

        existing_state = json.loads(incident.workflow_state_json or "{}")
        metrics_snapshot = existing_state.get("metrics_snapshot") or self.infra.get_system_metrics()
        raw_logs = json.loads(incident.raw_logs_json or "[]")

        db.add(
            AgentExecution(
                incident_id=incident.id,
                agent_name=self.name,
                status="STARTED",
                message=f"Incident {incident.id} ({incident.incident_type}) received for LangGraph orchestration.",
                input_summary=json.dumps(
                    {
                        "incident_type": incident.incident_type,
                        "affected_service": incident.affected_service,
                    }
                ),
                output_summary="{}",
            )
        )
        db.add(
            AuditLog(
                incident_id=incident.id,
                actor=self.name,
                event_type="WORKFLOW_STARTED",
                what_happened=f"Started LangGraph multi-agent workflow for {incident.incident_type}.",
                evidence_json=json.dumps({"affected_service": incident.affected_service}),
            )
        )
        incident.status = "INVESTIGATING"
        db.commit()

        initial_state: IncidentState = {
            "incident_id": incident.id,
            "incident_type": incident.incident_type,
            "affected_service": incident.affected_service,
            "simulate_failure": incident.simulate_failure,
            "metrics_snapshot": metrics_snapshot,
            "raw_logs": raw_logs,
            "workflow_status": "INVESTIGATING",
            "should_continue": True,
            "events": [
                {
                    "agent": self.name,
                    "status": "STARTED",
                    "detail": f"Initialized workflow for {incident.id}",
                }
            ],
        }

        graph = build_incident_graph(
            db=db,
            settings=self.settings,
            infra=self.infra,
            rag_min_relevance=rag_min_relevance,
        )
        final_state = graph.invoke(initial_state)

        final_status = final_state.get("workflow_status", "INVESTIGATING")
        incident.status = final_status
        incident.workflow_state_json = json.dumps(final_state, default=str)

        completion_msg = (
            final_state.get("escalation_reason")
            or final_state.get("error_message")
            or f"LangGraph workflow transitioned incident to status '{final_status}'."
        )
        db.add(
            AgentExecution(
                incident_id=incident.id,
                agent_name=self.name,
                status=final_status,
                message=completion_msg,
                input_summary="{}",
                output_summary=json.dumps({"workflow_status": final_status}),
            )
        )
        db.add(
            AuditLog(
                incident_id=incident.id,
                actor=self.name,
                event_type="WORKFLOW_STAGE_COMPLETED",
                what_happened=completion_msg,
                evidence_json=json.dumps({"workflow_status": final_status}),
            )
        )
        db.commit()
        db.refresh(incident)
        return dict(final_state)

    def approve_and_resume(
        self,
        db: Session,
        approval_id: str,
        decided_by: str = "demo-operator",
        comment: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Approve a pending action and resume the paused LangGraph workflow."""
        approval = db.query(ApprovalRequest).filter(ApprovalRequest.id == approval_id).first()
        if approval is None:
            raise ValueError(f"Approval request '{approval_id}' not found")
        if approval.status != "PENDING":
            raise ValueError(f"Approval request '{approval_id}' is already {approval.status}")

        incident = db.query(Incident).filter(Incident.id == approval.incident_id).first()
        if incident is None:
            raise ValueError(f"Incident '{approval.incident_id}' not found")

        now = datetime.now(timezone.utc)
        approval.status = "APPROVED"
        approval.decided_by = decided_by
        approval.decision_comment = comment
        approval.decided_at = now

        action_row = db.query(RemediationAction).filter(RemediationAction.id == approval.action_id).first()
        if action_row is not None:
            action_row.approval_status = "APPROVED"

        msg = f"Human approval GRANTED by {decided_by} for action '{approval.proposed_action}'."
        db.add(
            AgentExecution(
                incident_id=incident.id,
                agent_name="Human Approval",
                status="APPROVED",
                message=msg,
                input_summary=json.dumps({"approval_id": approval.id}),
                output_summary=json.dumps({"decided_by": decided_by, "comment": comment}),
            )
        )
        db.add(
            AuditLog(
                incident_id=incident.id,
                actor=decided_by,
                event_type="HUMAN_APPROVAL_GRANTED",
                what_happened=msg,
                proposed_action=approval.proposed_action,
                approval_required=True,
                approved_by=decided_by,
            )
        )
        db.commit()

        saved_state: IncidentState = json.loads(incident.workflow_state_json or "{}")
        saved_state["approval_result"] = {
            "approval_id": approval.id,
            "status": "APPROVED",
            "decided_by": decided_by,
            "decided_at": now.isoformat(),
            "comment": comment,
        }
        saved_state["should_continue"] = True

        resume_graph = build_resume_graph(db=db, settings=self.settings, infra=self.infra)
        resumed_state = resume_graph.invoke(saved_state)

        final_status = resumed_state.get("workflow_status", "EXECUTED")
        incident.status = final_status
        incident.workflow_state_json = json.dumps(resumed_state, default=str)

        db.add(
            AgentExecution(
                incident_id=incident.id,
                agent_name=self.name,
                status=final_status,
                message=f"Resumed workflow after approval; incident status='{final_status}'.",
                input_summary=json.dumps({"approval_id": approval.id}),
                output_summary=json.dumps({"workflow_status": final_status}),
            )
        )
        db.commit()
        db.refresh(approval)
        db.refresh(incident)
        return {"approval": approval, "incident": incident, "workflow_state": dict(resumed_state)}

    def reject_and_escalate(
        self,
        db: Session,
        approval_id: str,
        decided_by: str = "demo-operator",
        comment: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Reject a pending action, guarantee non-execution, and escalate the incident."""
        approval = db.query(ApprovalRequest).filter(ApprovalRequest.id == approval_id).first()
        if approval is None:
            raise ValueError(f"Approval request '{approval_id}' not found")
        if approval.status != "PENDING":
            raise ValueError(f"Approval request '{approval_id}' is already {approval.status}")

        incident = db.query(Incident).filter(Incident.id == approval.incident_id).first()
        if incident is None:
            raise ValueError(f"Incident '{approval.incident_id}' not found")

        now = datetime.now(timezone.utc)
        approval.status = "REJECTED"
        approval.decided_by = decided_by
        approval.decision_comment = comment
        approval.decided_at = now

        action_row = db.query(RemediationAction).filter(RemediationAction.id == approval.action_id).first()
        if action_row is not None:
            action_row.approval_status = "REJECTED"
            action_row.execution_status = "REJECTED_NOT_EXECUTED"

        saved_state: Dict[str, Any] = json.loads(incident.workflow_state_json or "{}")
        saved_state["approval_result"] = {
            "approval_id": approval.id,
            "status": "REJECTED",
            "decided_by": decided_by,
            "decided_at": now.isoformat(),
            "comment": comment,
        }
        saved_state["workflow_status"] = "ESCALATED"
        saved_state["should_continue"] = False
        saved_state["escalation_reason"] = (
            f"Proposed action '{approval.proposed_action}' rejected by {decided_by}; escalated for manual remediation."
        )

        incident.status = "ESCALATED"
        incident.workflow_state_json = json.dumps(saved_state, default=str)

        msg = f"Human approval REJECTED by {decided_by} for '{approval.proposed_action}'. Action blocked and incident escalated."
        db.add(
            AgentExecution(
                incident_id=incident.id,
                agent_name="Human Approval",
                status="REJECTED",
                message=msg,
                input_summary=json.dumps({"approval_id": approval.id}),
                output_summary=json.dumps({"decided_by": decided_by, "executed": False}),
            )
        )
        db.add(
            AuditLog(
                incident_id=incident.id,
                actor=decided_by,
                event_type="HUMAN_APPROVAL_REJECTED",
                what_happened=msg,
                proposed_action=approval.proposed_action,
                approval_required=True,
                approved_by=f"REJECTED:{decided_by}",
                resolved=False,
                rollback_required=False,
            )
        )
        db.commit()
        db.refresh(approval)
        db.refresh(incident)
        return {"approval": approval, "incident": incident, "workflow_state": saved_state}
