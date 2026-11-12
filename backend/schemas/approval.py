"""Pydantic schemas for human-in-the-loop approval requests and decisions."""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class ApprovalDecisionRequest(BaseModel):
    """Request payload for approving or rejecting a pending remediation action."""

    decided_by: str = Field(default="demo-operator", min_length=1, max_length=128)
    comment: Optional[str] = Field(default=None, max_length=500)


class ApprovalRequestResponse(BaseModel):
    """Representation of a pending or decided approval request."""

    id: str
    incident_id: str
    action_id: str
    proposed_action: str
    reason: str
    risk_level: str
    expected_outcome: str
    status: str
    decided_by: Optional[str] = None
    decision_comment: Optional[str] = None
    requested_at: datetime
    decided_at: Optional[datetime] = None


class ApprovalDecisionResponse(BaseModel):
    """Outcome of approving or rejecting a remediation action."""

    approval: ApprovalRequestResponse
    incident_id: str
    incident_status: str
    executed: bool
    message: str
