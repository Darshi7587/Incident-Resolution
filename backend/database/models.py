"""SQLAlchemy ORM models for incident tracking, agent execution, and audit trails."""

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.database.db import Base


def _utcnow() -> datetime:
    """Return timezone-aware UTC timestamp."""
    return datetime.now(timezone.utc)


class Incident(Base):
    """Primary incident record."""

    __tablename__ = "incidents"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    incident_type: Mapped[str] = mapped_column(String(64), nullable=False)
    severity: Mapped[str] = mapped_column(String(32), default="UNKNOWN", nullable=False)
    affected_service: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="DETECTED", nullable=False)
    summary: Mapped[str] = mapped_column(Text, default="", nullable=False)
    is_simulated: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    simulate_failure: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    detected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)
    resolved_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    simulated_duration_seconds: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    raw_logs_json: Mapped[str] = mapped_column(Text, default="[]", nullable=False)
    workflow_state_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)

    agent_executions = relationship("AgentExecution", back_populates="incident", cascade="all, delete-orphan")
    monitoring_metrics = relationship("MonitoringMetric", back_populates="incident", cascade="all, delete-orphan")
    root_cause_analyses = relationship("RootCauseAnalysis", back_populates="incident", cascade="all, delete-orphan")
    retrieved_runbooks = relationship("RetrievedRunbook", back_populates="incident", cascade="all, delete-orphan")
    remediation_actions = relationship("RemediationAction", back_populates="incident", cascade="all, delete-orphan")
    approval_requests = relationship("ApprovalRequest", back_populates="incident", cascade="all, delete-orphan")
    validation_results = relationship("ValidationResult", back_populates="incident", cascade="all, delete-orphan")
    audit_logs = relationship("AuditLog", back_populates="incident", cascade="all, delete-orphan")


class AgentExecution(Base):
    """Execution record for each agent step in the workflow."""

    __tablename__ = "agent_executions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    incident_id: Mapped[str] = mapped_column(String(64), ForeignKey("incidents.id"), nullable=False, index=True)
    agent_name: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    message: Mapped[str] = mapped_column(Text, default="", nullable=False)
    input_summary: Mapped[str] = mapped_column(Text, default="{}", nullable=False)
    output_summary: Mapped[str] = mapped_column(Text, default="{}", nullable=False)
    executed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)

    incident = relationship("Incident", back_populates="agent_executions")


class MonitoringMetric(Base):
    """Simulated system metrics snapshots captured before and after remediation."""

    __tablename__ = "monitoring_metrics"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    incident_id: Mapped[str] = mapped_column(String(64), ForeignKey("incidents.id"), nullable=False, index=True)
    phase: Mapped[str] = mapped_column(String(32), default="BEFORE", nullable=False)
    cpu_usage: Mapped[float] = mapped_column(Float, nullable=False)
    memory_usage: Mapped[float] = mapped_column(Float, nullable=False)
    disk_usage: Mapped[float] = mapped_column(Float, nullable=False)
    service_name: Mapped[str] = mapped_column(String(128), nullable=False)
    service_status: Mapped[str] = mapped_column(String(32), nullable=False)
    db_connected: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    violations_json: Mapped[str] = mapped_column(Text, default="[]", nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)

    incident = relationship("Incident", back_populates="monitoring_metrics")


class RootCauseAnalysis(Base):
    """Probable root cause hypotheses and supporting evidence."""

    __tablename__ = "root_cause_analysis"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    incident_id: Mapped[str] = mapped_column(String(64), ForeignKey("incidents.id"), nullable=False, index=True)
    probable_cause: Mapped[str] = mapped_column(Text, nullable=False)
    confidence_score: Mapped[float] = mapped_column(Float, nullable=False)
    reasoning_source: Mapped[str] = mapped_column(String(32), nullable=False)  # OLLAMA_LLM or DETERMINISTIC_FALLBACK
    reasoning_summary: Mapped[str] = mapped_column(Text, nullable=False)
    supporting_evidence_json: Mapped[str] = mapped_column(Text, default="[]", nullable=False)
    hypotheses_json: Mapped[str] = mapped_column(Text, default="[]", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)

    incident = relationship("Incident", back_populates="root_cause_analyses")


class RetrievedRunbook(Base):
    """Semantic RAG retrieval results from ChromaDB runbooks."""

    __tablename__ = "retrieved_runbooks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    incident_id: Mapped[str] = mapped_column(String(64), ForeignKey("incidents.id"), nullable=False, index=True)
    runbook_name: Mapped[str] = mapped_column(String(128), nullable=False)
    section_title: Mapped[str] = mapped_column(String(256), default="", nullable=False)
    excerpt: Mapped[str] = mapped_column(Text, nullable=False)
    relevance_score: Mapped[float] = mapped_column(Float, nullable=False)
    query_text: Mapped[str] = mapped_column(Text, default="", nullable=False)
    retrieved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)

    incident = relationship("Incident", back_populates="retrieved_runbooks")


class RemediationAction(Base):
    """Proposed, approved/rejected, and executed simulated remediation actions."""

    __tablename__ = "remediation_actions"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    incident_id: Mapped[str] = mapped_column(String(64), ForeignKey("incidents.id"), nullable=False, index=True)
    action_name: Mapped[str] = mapped_column(String(128), nullable=False)
    action_description: Mapped[str] = mapped_column(Text, nullable=False)
    rationale: Mapped[str] = mapped_column(Text, default="", nullable=False)
    expected_outcome: Mapped[str] = mapped_column(Text, default="", nullable=False)
    risk_level: Mapped[str] = mapped_column(String(16), nullable=False)  # LOW, MEDIUM, HIGH
    approval_status: Mapped[str] = mapped_column(String(32), default="PENDING", nullable=False)
    execution_status: Mapped[str] = mapped_column(String(32), default="PENDING", nullable=False)
    before_state_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)
    after_state_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)
    rollback_info_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)
    executed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    incident = relationship("Incident", back_populates="remediation_actions")


class ApprovalRequest(Base):
    """Human-in-the-loop approval request tied to a remediation action."""

    __tablename__ = "approval_requests"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    incident_id: Mapped[str] = mapped_column(String(64), ForeignKey("incidents.id"), nullable=False, index=True)
    action_id: Mapped[str] = mapped_column(String(64), ForeignKey("remediation_actions.id"), nullable=False)
    proposed_action: Mapped[str] = mapped_column(String(128), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    risk_level: Mapped[str] = mapped_column(String(16), nullable=False)
    expected_outcome: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="PENDING", nullable=False)  # PENDING, APPROVED, REJECTED
    decided_by: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    decision_comment: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)
    decided_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    incident = relationship("Incident", back_populates="approval_requests")


class ValidationResult(Base):
    """Post-remediation validation outcome and before/after metric comparison."""

    __tablename__ = "validation_results"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    incident_id: Mapped[str] = mapped_column(String(64), ForeignKey("incidents.id"), nullable=False, index=True)
    is_recovered: Mapped[bool] = mapped_column(Boolean, nullable=False)
    final_status: Mapped[str] = mapped_column(String(32), nullable=False)  # RESOLVED, FAILED, ESCALATED
    before_metrics_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)
    after_metrics_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)
    rollback_triggered: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    rollback_status: Mapped[str] = mapped_column(String(64), default="NOT_NEEDED", nullable=False)
    validation_notes: Mapped[str] = mapped_column(Text, default="", nullable=False)
    validated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)

    incident = relationship("Incident", back_populates="validation_results")


class AuditLog(Base):
    """Immutable-style audit trail capturing every incident workflow decision and action."""

    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    incident_id: Mapped[str] = mapped_column(String(64), ForeignKey("incidents.id"), nullable=False, index=True)
    actor: Mapped[str] = mapped_column(String(64), nullable=False)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    what_happened: Mapped[str] = mapped_column(Text, nullable=False)
    evidence_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)
    proposed_action: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    approval_required: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    approved_by: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    action_executed: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    resolved: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    rollback_required: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)

    incident = relationship("Incident", back_populates="audit_logs")
