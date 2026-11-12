"""Audit trail and auditable incident resolution report generator."""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from backend.database.models import (
    AgentExecution,
    ApprovalRequest,
    AuditLog,
    Incident,
    MonitoringMetric,
    RemediationAction,
    RetrievedRunbook,
    RootCauseAnalysis,
    ValidationResult,
)


def build_incident_report(db: Session, incident_id: str) -> Optional[Dict[str, Any]]:
    """Assemble a complete auditable incident resolution report from SQLite records."""
    incident = db.query(Incident).filter(Incident.id == incident_id).first()
    if incident is None:
        return None

    before_metric = (
        db.query(MonitoringMetric)
        .filter(MonitoringMetric.incident_id == incident_id, MonitoringMetric.phase == "BEFORE")
        .order_by(MonitoringMetric.id.asc())
        .first()
    )
    after_metric = (
        db.query(MonitoringMetric)
        .filter(MonitoringMetric.incident_id == incident_id, MonitoringMetric.phase == "AFTER")
        .order_by(MonitoringMetric.id.desc())
        .first()
    )
    rca = (
        db.query(RootCauseAnalysis)
        .filter(RootCauseAnalysis.incident_id == incident_id)
        .order_by(RootCauseAnalysis.id.desc())
        .first()
    )
    runbooks = (
        db.query(RetrievedRunbook)
        .filter(RetrievedRunbook.incident_id == incident_id)
        .order_by(RetrievedRunbook.relevance_score.desc())
        .all()
    )
    actions = (
        db.query(RemediationAction)
        .filter(RemediationAction.incident_id == incident_id)
        .order_by(RemediationAction.created_at.asc())
        .all()
    )
    approvals = (
        db.query(ApprovalRequest)
        .filter(ApprovalRequest.incident_id == incident_id)
        .order_by(ApprovalRequest.requested_at.asc())
        .all()
    )
    validation = (
        db.query(ValidationResult)
        .filter(ValidationResult.incident_id == incident_id)
        .order_by(ValidationResult.id.desc())
        .first()
    )
    timeline = (
        db.query(AgentExecution)
        .filter(AgentExecution.incident_id == incident_id)
        .order_by(AgentExecution.executed_at.asc(), AgentExecution.id.asc())
        .all()
    )
    audit_logs = (
        db.query(AuditLog)
        .filter(AuditLog.incident_id == incident_id)
        .order_by(AuditLog.created_at.asc(), AuditLog.id.asc())
        .all()
    )

    def _metric_dict(m: Optional[MonitoringMetric]) -> Dict[str, Any]:
        if m is None:
            return {}
        return {
            "phase": m.phase,
            "cpu_usage": m.cpu_usage,
            "memory_usage": m.memory_usage,
            "disk_usage": m.disk_usage,
            "service_name": m.service_name,
            "service_status": m.service_status,
            "db_connected": m.db_connected,
            "violations": json.loads(m.violations_json or "[]"),
            "recorded_at": m.recorded_at.isoformat(),
        }

    report: Dict[str, Any] = {
        "incident_summary": {
            "incident_id": incident.id,
            "incident_type": incident.incident_type,
            "severity": incident.severity,
            "affected_service": incident.affected_service,
            "status": incident.status,
            "summary": incident.summary,
            "is_simulated": incident.is_simulated,
            "simulate_failure": incident.simulate_failure,
            "detected_at": incident.detected_at.isoformat(),
            "resolved_at": incident.resolved_at.isoformat() if incident.resolved_at else None,
            "simulated_duration_seconds": incident.simulated_duration_seconds,
        },
        "root_cause_analysis": (
            {
                "probable_cause": rca.probable_cause,
                "confidence_score": rca.confidence_score,
                "reasoning_source": rca.reasoning_source,
                "reasoning_summary": rca.reasoning_summary,
                "supporting_evidence": json.loads(rca.supporting_evidence_json or "[]"),
                "hypotheses": json.loads(rca.hypotheses_json or "[]"),
            }
            if rca
            else None
        ),
        "retrieved_runbooks": [
            {
                "runbook_name": rb.runbook_name,
                "section_title": rb.section_title,
                "relevance_score": rb.relevance_score,
                "excerpt": rb.excerpt,
            }
            for rb in runbooks
        ],
        "remediation_actions": [
            {
                "action_id": act.id,
                "action_name": act.action_name,
                "action_description": act.action_description,
                "rationale": act.rationale,
                "expected_outcome": act.expected_outcome,
                "risk_level": act.risk_level,
                "approval_status": act.approval_status,
                "execution_status": act.execution_status,
                "before_state": json.loads(act.before_state_json or "{}"),
                "after_state": json.loads(act.after_state_json or "{}"),
                "rollback_info": json.loads(act.rollback_info_json or "{}"),
                "executed_at": act.executed_at.isoformat() if act.executed_at else None,
            }
            for act in actions
        ],
        "approval_details": [
            {
                "approval_id": ap.id,
                "proposed_action": ap.proposed_action,
                "risk_level": ap.risk_level,
                "status": ap.status,
                "decided_by": ap.decided_by,
                "decision_comment": ap.decision_comment,
                "requested_at": ap.requested_at.isoformat(),
                "decided_at": ap.decided_at.isoformat() if ap.decided_at else None,
            }
            for ap in approvals
        ],
        "before_and_after_metrics": {
            "before": _metric_dict(before_metric),
            "after": _metric_dict(after_metric),
        },
        "validation_outcome": (
            {
                "is_recovered": validation.is_recovered,
                "final_status": validation.final_status,
                "rollback_triggered": validation.rollback_triggered,
                "rollback_status": validation.rollback_status,
                "validation_notes": validation.validation_notes,
                "validated_at": validation.validated_at.isoformat(),
            }
            if validation
            else None
        ),
        "raw_logs": json.loads(incident.raw_logs_json or "[]"),
        "agent_timeline": [
            {
                "timestamp": ex.executed_at.isoformat(),
                "agent_name": ex.agent_name,
                "status": ex.status,
                "message": ex.message,
            }
            for ex in timeline
        ],
        "audit_events": [
            {
                "timestamp": log.created_at.isoformat(),
                "actor": log.actor,
                "event_type": log.event_type,
                "what_happened": log.what_happened,
                "proposed_action": log.proposed_action,
                "approval_required": log.approval_required,
                "approved_by": log.approved_by,
                "action_executed": log.action_executed,
                "resolved": log.resolved,
                "rollback_required": log.rollback_required,
            }
            for log in audit_logs
        ],
    }
    return report


def render_report_text(report: Dict[str, Any]) -> str:
    """Render an auditable incident report dictionary into human-readable plain text."""
    inc = report["incident_summary"]
    lines: List[str] = [
        "================================================================",
        f"AUTONOMOUS IT INCIDENT RESOLUTION REPORT — {inc['incident_id']}",
        "================================================================",
        f"Incident Type      : {inc['incident_type']}",
        f"Severity           : {inc['severity']}",
        f"Affected Service   : {inc['affected_service']}",
        f"Final Status       : {inc['status']}",
        f"Simulated          : {inc['is_simulated']}",
        f"Detected At        : {inc['detected_at']}",
        f"Resolved At        : {inc['resolved_at'] or 'N/A'}",
        f"Resolution Duration: {inc['simulated_duration_seconds'] or 'N/A'} sec",
        f"Summary            : {inc['summary']}",
        "",
        "--- ROOT CAUSE ANALYSIS ---",
    ]
    rca = report.get("root_cause_analysis")
    if rca:
        lines.extend(
            [
                f"Probable Cause : {rca['probable_cause']}",
                f"Confidence     : {rca['confidence_score']}",
                f"Source         : {rca['reasoning_source']}",
                f"Reasoning      : {rca['reasoning_summary']}",
            ]
        )
    else:
        lines.append("No RCA generated.")

    lines.extend(["", "--- RETRIEVED RUNBOOKS (RAG) ---"])
    for rb in report.get("retrieved_runbooks", [])[:3]:
        lines.append(f"- {rb['runbook_name']} :: {rb['section_title']} (score={rb['relevance_score']})")

    lines.extend(["", "--- REMEDIATION & APPROVALS ---"])
    for act in report.get("remediation_actions", []):
        lines.append(
            f"- {act['action_name']} [{act['risk_level']}] | Approval={act['approval_status']} | Exec={act['execution_status']}"
        )
    for ap in report.get("approval_details", []):
        lines.append(
            f"- Approval {ap['approval_id']}: {ap['status']} by {ap['decided_by'] or 'N/A'} ({ap['decision_comment'] or 'no comment'})"
        )

    lines.extend(["", "--- BEFORE & AFTER METRICS ---"])
    before = report["before_and_after_metrics"].get("before") or {}
    after = report["before_and_after_metrics"].get("after") or {}
    if before:
        lines.append(
            f"BEFORE: CPU={before.get('cpu_usage')}%, Mem={before.get('memory_usage')}%, Disk={before.get('disk_usage')}%, Status={before.get('service_status')}, DB={before.get('db_connected')}"
        )
    if after:
        lines.append(
            f"AFTER : CPU={after.get('cpu_usage')}%, Mem={after.get('memory_usage')}%, Disk={after.get('disk_usage')}%, Status={after.get('service_status')}, DB={after.get('db_connected')}"
        )

    lines.extend(["", "--- VALIDATION OUTCOME ---"])
    val = report.get("validation_outcome")
    if val:
        lines.append(
            f"Recovered={val['is_recovered']} | Final={val['final_status']} | Rollback={val['rollback_status']} | Notes: {val['validation_notes']}"
        )
    else:
        lines.append("No validation executed.")

    lines.extend(["", "--- AUDIT EVENTS ---"])
    for ev in report.get("audit_events", []):
        lines.append(f"[{ev['timestamp']}] {ev['actor']} ({ev['event_type']}): {ev['what_happened']}")

    return "\n".join(lines)
