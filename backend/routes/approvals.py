"""Human-in-the-loop approval REST endpoints."""

from typing import List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from backend.agents.orchestrator import OrchestratorAgent
from backend.database.db import get_db
from backend.database.models import ApprovalRequest
from backend.schemas.approval import (
    ApprovalDecisionRequest,
    ApprovalDecisionResponse,
    ApprovalRequestResponse,
)

router = APIRouter(prefix="/approvals", tags=["Human Approvals"])


def _to_approval_response(req: ApprovalRequest) -> ApprovalRequestResponse:
    return ApprovalRequestResponse(
        id=req.id,
        incident_id=req.incident_id,
        action_id=req.action_id,
        proposed_action=req.proposed_action,
        reason=req.reason,
        risk_level=req.risk_level,
        expected_outcome=req.expected_outcome,
        status=req.status,
        decided_by=req.decided_by,
        decision_comment=req.decision_comment,
        requested_at=req.requested_at,
        decided_at=req.decided_at,
    )


@router.get("/pending", response_model=List[ApprovalRequestResponse])
def list_pending_approvals(db: Session = Depends(get_db)) -> List[ApprovalRequestResponse]:
    """List all pending human approval requests."""
    pending = (
        db.query(ApprovalRequest)
        .filter(ApprovalRequest.status == "PENDING")
        .order_by(ApprovalRequest.requested_at.desc())
        .all()
    )
    return [_to_approval_response(r) for r in pending]


@router.post("/{approval_id}/approve", response_model=ApprovalDecisionResponse)
def approve_action(
    approval_id: str,
    payload: ApprovalDecisionRequest = ApprovalDecisionRequest(),
    db: Session = Depends(get_db),
) -> ApprovalDecisionResponse:
    """Approve a pending remediation action and resume the paused LangGraph workflow."""
    orchestrator = OrchestratorAgent()
    try:
        res = orchestrator.approve_and_resume(
            db=db,
            approval_id=approval_id,
            decided_by=payload.decided_by,
            comment=payload.comment,
        )
    except ValueError as exc:
        code = 404 if "not found" in str(exc).lower() else 409
        raise HTTPException(status_code=code, detail=str(exc)) from exc

    approval = res["approval"]
    incident = res["incident"]
    exec_res = res["workflow_state"].get("execution_result", {})
    return ApprovalDecisionResponse(
        approval=_to_approval_response(approval),
        incident_id=incident.id,
        incident_status=incident.status,
        executed=bool(exec_res.get("action_succeeded") is not None),
        message=exec_res.get("message", f"Approval granted and workflow transitioned to {incident.status}."),
    )


@router.post("/{approval_id}/reject", response_model=ApprovalDecisionResponse)
def reject_action(
    approval_id: str,
    payload: ApprovalDecisionRequest = ApprovalDecisionRequest(),
    db: Session = Depends(get_db),
) -> ApprovalDecisionResponse:
    """Reject a pending remediation action, preventing execution and escalating the incident."""
    orchestrator = OrchestratorAgent()
    try:
        res = orchestrator.reject_and_escalate(
            db=db,
            approval_id=approval_id,
            decided_by=payload.decided_by,
            comment=payload.comment,
        )
    except ValueError as exc:
        code = 404 if "not found" in str(exc).lower() else 409
        raise HTTPException(status_code=code, detail=str(exc)) from exc

    approval = res["approval"]
    incident = res["incident"]
    return ApprovalDecisionResponse(
        approval=_to_approval_response(approval),
        incident_id=incident.id,
        incident_status=incident.status,
        executed=False,
        message=res["workflow_state"].get("escalation_reason", "Action rejected and incident escalated."),
    )
