"""Agent 2: Monitoring Agent — evaluates simulated metrics against configurable thresholds."""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from backend.config import Settings, get_settings
from backend.database.models import AgentExecution, AuditLog, Incident, MonitoringMetric
from backend.services.incident_simulator import SimulatedInfrastructure


class MonitoringAgent:
    """Analyzes simulated infrastructure metrics, detects threshold violations, and classifies severity."""

    name = "Monitoring Agent"

    def __init__(
        self,
        settings: Optional[Settings] = None,
        infra: Optional[SimulatedInfrastructure] = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.infra = infra or SimulatedInfrastructure()

    def _evaluate_metric(
        self,
        metric_name: str,
        value: float,
        warning_threshold: float,
        critical_threshold: float,
        unit: str = "%",
    ) -> Optional[Dict[str, Any]]:
        if value >= critical_threshold:
            return {
                "metric": metric_name,
                "value": value,
                "unit": unit,
                "threshold": critical_threshold,
                "level": "CRITICAL",
                "message": f"{metric_name} at {value}{unit} exceeds critical threshold ({critical_threshold}{unit})",
            }
        if value >= warning_threshold:
            return {
                "metric": metric_name,
                "value": value,
                "unit": unit,
                "threshold": warning_threshold,
                "level": "WARNING",
                "message": f"{metric_name} at {value}{unit} exceeds warning threshold ({warning_threshold}{unit})",
            }
        return None

    def analyze(
        self,
        metrics: Optional[Dict[str, Any]] = None,
        incident_id: Optional[str] = None,
        db: Optional[Session] = None,
    ) -> Dict[str, Any]:
        """Inspect simulated system metrics, classify severity, and persist observations."""
        snapshot = metrics or self.infra.get_system_metrics()
        cpu = float(snapshot.get("cpu_usage", 0.0))
        memory = float(snapshot.get("memory_usage", 0.0))
        disk = float(snapshot.get("disk_usage", 0.0))
        services: Dict[str, str] = dict(snapshot.get("services", {}))
        db_connected = bool(snapshot.get("db_connected", True))

        violations: List[Dict[str, Any]] = []
        evidence: List[str] = []
        affected_services: List[str] = []

        for check in (
            self._evaluate_metric(
                "cpu_usage",
                cpu,
                self.settings.cpu_warning_threshold,
                self.settings.cpu_critical_threshold,
            ),
            self._evaluate_metric(
                "memory_usage",
                memory,
                self.settings.memory_warning_threshold,
                self.settings.memory_critical_threshold,
            ),
            self._evaluate_metric(
                "disk_usage",
                disk,
                self.settings.disk_warning_threshold,
                self.settings.disk_critical_threshold,
            ),
        ):
            if check:
                violations.append(check)
                evidence.append(check["message"])

        for svc_name, svc_status in services.items():
            if svc_status != "HEALTHY":
                affected_services.append(svc_name)
                level = "CRITICAL" if svc_status in {"FAILED", "UNREACHABLE"} else "WARNING"
                violations.append(
                    {
                        "metric": f"service:{svc_name}",
                        "value": svc_status,
                        "unit": "status",
                        "threshold": "HEALTHY",
                        "level": level,
                        "message": f"Service '{svc_name}' is in {svc_status} state",
                    }
                )
                evidence.append(f"Service '{svc_name}' reported status {svc_status}")

        if not db_connected:
            if "db-server" not in affected_services:
                affected_services.append("db-server")
            violations.append(
                {
                    "metric": "db_connected",
                    "value": False,
                    "unit": "boolean",
                    "threshold": True,
                    "level": "CRITICAL",
                    "message": "Database connectivity check failed (db-server unreachable)",
                }
            )
            evidence.append("Database connectivity is DOWN (db_connected=False)")

        levels = {v["level"] for v in violations}
        if "CRITICAL" in levels:
            severity = "CRITICAL"
        elif "WARNING" in levels:
            severity = "WARNING"
        else:
            severity = "NORMAL"

        if not evidence:
            evidence.append(
                f"All metrics within normal thresholds (CPU={cpu}%, Memory={memory}%, Disk={disk}%)"
            )

        result: Dict[str, Any] = {
            "agent": self.name,
            "status": "COMPLETED",
            "severity": severity,
            "anomaly_detected": severity != "NORMAL",
            "metrics": {
                "cpu_usage": cpu,
                "memory_usage": memory,
                "disk_usage": disk,
                "disk_available_gb": snapshot.get("disk_available_gb"),
                "filesystem": snapshot.get("filesystem", "/dev/sda1"),
                "db_connected": db_connected,
                "services": services,
                "cpu_history": snapshot.get("cpu_history", []),
            },
            "thresholds": {
                "cpu_warning": self.settings.cpu_warning_threshold,
                "cpu_critical": self.settings.cpu_critical_threshold,
                "memory_warning": self.settings.memory_warning_threshold,
                "memory_critical": self.settings.memory_critical_threshold,
                "disk_warning": self.settings.disk_warning_threshold,
                "disk_critical": self.settings.disk_critical_threshold,
            },
            "threshold_violations": violations,
            "affected_services": affected_services,
            "evidence": evidence,
        }

        if db is not None and incident_id is not None:
            incident = db.query(Incident).filter(Incident.id == incident_id).first()
            if incident is not None:
                incident.severity = severity
                if affected_services and incident.affected_service not in affected_services:
                    incident.affected_service = affected_services[0]

                primary_service = incident.affected_service
                metric_record = (
                    db.query(MonitoringMetric)
                    .filter(MonitoringMetric.incident_id == incident_id, MonitoringMetric.phase == "BEFORE")
                    .first()
                )
                if metric_record is not None:
                    metric_record.violations_json = json.dumps(violations)
                else:
                    db.add(
                        MonitoringMetric(
                            incident_id=incident_id,
                            phase="BEFORE",
                            cpu_usage=cpu,
                            memory_usage=memory,
                            disk_usage=disk,
                            service_name=primary_service,
                            service_status=services.get(primary_service, "UNKNOWN"),
                            db_connected=db_connected,
                            violations_json=json.dumps(violations),
                        )
                    )

                summary_msg = (
                    f"{severity} severity detected ({len(violations)} violation(s))"
                    if violations
                    else "All monitored metrics within normal operating thresholds"
                )
                db.add(
                    AgentExecution(
                        incident_id=incident_id,
                        agent_name=self.name,
                        status="COMPLETED",
                        message=summary_msg,
                        input_summary=json.dumps({"cpu": cpu, "memory": memory, "disk": disk}),
                        output_summary=json.dumps(
                            {
                                "severity": severity,
                                "violation_count": len(violations),
                                "affected_services": affected_services,
                            }
                        ),
                    )
                )
                db.add(
                    AuditLog(
                        incident_id=incident_id,
                        actor=self.name,
                        event_type="MONITORING_ANALYZED",
                        what_happened=summary_msg,
                        evidence_json=json.dumps(violations),
                    )
                )
                db.commit()

        return result
