"""Agent 7: Validation Agent — verifies post-remediation recovery and triggers rollback if failed."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from backend.config import Settings, get_settings
from backend.database.models import (
    AgentExecution,
    AuditLog,
    Incident,
    MonitoringMetric,
    ValidationResult,
)
from backend.services.incident_simulator import SimulatedInfrastructure
from backend.services.remediation_executor import RemediationExecutor


class ValidationAgent:
    """Compares before-and-after metrics, validates service health, and enforces rollback on failure."""

    name = "Validation Agent"

    def __init__(
        self,
        settings: Optional[Settings] = None,
        infra: Optional[SimulatedInfrastructure] = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.infra = infra or SimulatedInfrastructure()
        self.executor = RemediationExecutor(infra=self.infra)

    def validate(
        self,
        incident_id: str,
        target_service: str,
        before_metrics: Dict[str, Any],
        execution_result: Dict[str, Any],
        db: Optional[Session] = None,
    ) -> Dict[str, Any]:
        """Verify system recovery after remediation; rollback and escalate if still unhealthy."""
        after_metrics = self.infra.get_system_metrics()
        health_check = self.infra.check_service_health(target_service)

        cpu_ok = float(after_metrics.get("cpu_usage", 0.0)) < self.settings.cpu_warning_threshold
        mem_ok = float(after_metrics.get("memory_usage", 0.0)) < self.settings.memory_warning_threshold
        disk_ok = float(after_metrics.get("disk_usage", 0.0)) < self.settings.disk_warning_threshold
        service_status = after_metrics.get("services", {}).get(target_service, "UNKNOWN")
        service_ok = service_status == "HEALTHY"
        db_ok = bool(after_metrics.get("db_connected", True))

        action_succeeded = bool(execution_result.get("action_succeeded", False))
        is_recovered = bool(action_succeeded and cpu_ok and mem_ok and disk_ok and service_ok and db_ok)

        rollback_triggered = False
        rollback_status = "NOT_NEEDED"
        notes: List[str] = []

        if is_recovered:
            final_status = "RESOLVED"
            notes.append(
                f"Recovery verified for '{target_service}': "
                f"CPU {before_metrics.get('cpu_usage')}% -> {after_metrics.get('cpu_usage')}%, "
                f"Disk {before_metrics.get('disk_usage')}% -> {after_metrics.get('disk_usage')}%, "
                f"Service={service_status}, db_connected={db_ok}."
            )
        else:
            rollback_triggered = True
            rb_res = self.executor.rollback_simulated_action(
                before_state=execution_result.get("before_state") or before_metrics,
                action_id=execution_result.get("action_id"),
                incident_id=incident_id,
                db=db,
            )
            rollback_status = "ROLLED_BACK" if rb_res.get("rolled_back") else "ROLLBACK_FAILED"
            final_status = "ESCALATED" if rb_res.get("rolled_back") else "FAILED"
            notes.append(
                f"Post-remediation validation FAILED for '{target_service}' "
                f"(cpu_ok={cpu_ok}, disk_ok={disk_ok}, service_ok={service_ok}, db_ok={db_ok}). "
                f"Rollback status: {rollback_status}. Escalating incident for manual investigation."
            )

        validation_summary = " ".join(notes)
        now = datetime.now(timezone.utc)

        result = {
            "agent": self.name,
            "status": "COMPLETED",
            "is_recovered": is_recovered,
            "final_status": final_status,
            "before_metrics": before_metrics,
            "after_metrics": after_metrics,
            "health_check": health_check,
            "rollback_triggered": rollback_triggered,
            "rollback_status": rollback_status,
            "validation_notes": validation_summary,
            "validated_at": now.isoformat(),
        }

        if db is not None:
            incident = db.query(Incident).filter(Incident.id == incident_id).first()
            if incident is not None:
                incident.status = final_status
                if is_recovered:
                    incident.resolved_at = now
                detected_at = incident.detected_at
                if detected_at.tzinfo is None:
                    detected_at = detected_at.replace(tzinfo=timezone.utc)
                incident.simulated_duration_seconds = round(max(0.5, (now - detected_at).total_seconds()), 2)

            db.add(
                MonitoringMetric(
                    incident_id=incident_id,
                    phase="AFTER",
                    cpu_usage=float(after_metrics.get("cpu_usage", 0.0)),
                    memory_usage=float(after_metrics.get("memory_usage", 0.0)),
                    disk_usage=float(after_metrics.get("disk_usage", 0.0)),
                    service_name=target_service,
                    service_status=service_status,
                    db_connected=db_ok,
                    violations_json="[]",
                )
            )
            db.add(
                ValidationResult(
                    incident_id=incident_id,
                    is_recovered=is_recovered,
                    final_status=final_status,
                    before_metrics_json=json.dumps(before_metrics),
                    after_metrics_json=json.dumps(after_metrics),
                    rollback_triggered=rollback_triggered,
                    rollback_status=rollback_status,
                    validation_notes=validation_summary,
                )
            )
            db.add(
                AgentExecution(
                    incident_id=incident_id,
                    agent_name=self.name,
                    status=final_status,
                    message=validation_summary,
                    input_summary=json.dumps({"target_service": target_service}),
                    output_summary=json.dumps(
                        {
                            "is_recovered": is_recovered,
                            "final_status": final_status,
                            "rollback_triggered": rollback_triggered,
                        }
                    ),
                )
            )
            db.add(
                AuditLog(
                    incident_id=incident_id,
                    actor=self.name,
                    event_type="RECOVERY_VALIDATED" if is_recovered else "VALIDATION_FAILED_ROLLBACK",
                    what_happened=validation_summary,
                    evidence_json=json.dumps({"before": before_metrics, "after": after_metrics}),
                    resolved=is_recovered,
                    rollback_required=rollback_triggered,
                )
            )
            db.commit()

        return result
