"""Simulated IT infrastructure state and multi-scenario incident generator."""

from __future__ import annotations

import json
import uuid
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from backend.config import BASE_DIR
from backend.database.models import AuditLog, Incident, MonitoringMetric
from backend.schemas.incident import ScenarioType


DEFAULT_STATE: Dict[str, Any] = {
    "cpu_usage": 24.0,
    "memory_usage": 42.0,
    "disk_usage": 48.0,
    "disk_total_gb": 100.0,
    "disk_available_gb": 52.0,
    "filesystem": "/dev/sda1",
    "temp_files_gb": 2.0,
    "db_server_status": "HEALTHY",
    "db_connected": True,
    "services": {
        "application-server": "HEALTHY",
        "storage-service": "HEALTHY",
        "payment-api": "HEALTHY",
        "db-server": "HEALTHY",
    },
    "cpu_history": [22.0, 23.0, 24.0],
    "updated_at": datetime.now(timezone.utc).isoformat(),
    "is_simulated": True,
}


class SimulatedInfrastructure:
    """Manages isolated simulated infrastructure metrics, services, and state persistence."""

    def __init__(self, state_file: Optional[Path] = None) -> None:
        self.state_file = state_file or (BASE_DIR / "data" / "runtime" / "sim_state.json")
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        if not self.state_file.exists():
            self._save_state(deepcopy(DEFAULT_STATE))

    def _load_state(self) -> Dict[str, Any]:
        if not self.state_file.exists():
            state = deepcopy(DEFAULT_STATE)
            self._save_state(state)
            return state
        with self.state_file.open("r", encoding="utf-8") as fh:
            return json.load(fh)

    def _save_state(self, state: Dict[str, Any]) -> Dict[str, Any]:
        state["updated_at"] = datetime.now(timezone.utc).isoformat()
        state["is_simulated"] = True
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        with self.state_file.open("w", encoding="utf-8") as fh:
            json.dump(state, fh, indent=2)
        return state

    def reset(self) -> Dict[str, Any]:
        """Reset all simulated services and resource metrics to healthy baseline."""
        return self._save_state(deepcopy(DEFAULT_STATE))

    def get_system_metrics(self) -> Dict[str, Any]:
        """Return current simulated system metrics and service statuses."""
        return self._load_state()

    def update_state(self, updates: Dict[str, Any]) -> Dict[str, Any]:
        """Apply partial updates to simulated infrastructure state."""
        state = self._load_state()
        for key, value in updates.items():
            if key == "services" and isinstance(value, dict):
                state["services"].update(value)
            else:
                state[key] = value
        return self._save_state(state)

    def check_service_health(self, service_name: str) -> Dict[str, Any]:
        """Check simulated health for a specific service and related dependencies."""
        state = self._load_state()
        status = state["services"].get(service_name, "UNKNOWN")
        healthy = (
            status == "HEALTHY"
            and state["cpu_usage"] < 70.0
            and state["memory_usage"] < 75.0
            and state["disk_usage"] < 80.0
            and (service_name != "payment-api" or state["db_connected"])
        )
        return {
            "service_name": service_name,
            "service_status": status,
            "db_connected": state["db_connected"],
            "cpu_usage": state["cpu_usage"],
            "memory_usage": state["memory_usage"],
            "disk_usage": state["disk_usage"],
            "healthy": healthy,
            "checked_at": datetime.now(timezone.utc).isoformat(),
            "is_simulated": True,
        }


class IncidentSimulator:
    """Generates realistic simulated incidents, metrics, and logs for the 3 demo scenarios."""

    def __init__(self, infra: Optional[SimulatedInfrastructure] = None) -> None:
        self.infra = infra or SimulatedInfrastructure()

    def _build_scenario_payload(self, scenario: ScenarioType) -> Dict[str, Any]:
        if scenario == ScenarioType.HIGH_CPU:
            state = self.infra.update_state(
                {
                    "cpu_usage": 95.0,
                    "memory_usage": 60.0,
                    "disk_usage": 55.0,
                    "disk_available_gb": 45.0,
                    "temp_files_gb": 3.0,
                    "db_server_status": "HEALTHY",
                    "db_connected": True,
                    "services": {
                        "application-server": "DEGRADED",
                        "storage-service": "HEALTHY",
                        "payment-api": "HEALTHY",
                        "db-server": "HEALTHY",
                    },
                    "cpu_history": [45.0, 72.0, 95.0],
                }
            )
            logs = [
                "[10:00:01] INFO application-server CPU utilization: 45%",
                "[10:00:02] WARNING application-server CPU utilization: 72%",
                "[10:00:03] CRITICAL application-server CPU utilization: 95%",
                "[10:00:04] ERROR application-server CPU_THRESHOLD_EXCEEDED: runaway worker thread pool (pid=4821)",
                "[10:00:05] ERROR application-server resource exhaustion detected; request queue latency rising",
            ]
            return {
                "incident_type": ScenarioType.HIGH_CPU.value,
                "affected_service": "application-server",
                "initial_severity": "CRITICAL",
                "summary": "Simulated CPU spike to 95% on application-server (45% -> 72% -> 95%).",
                "logs": logs,
                "metrics": state,
            }

        if scenario == ScenarioType.DISK_FULL:
            state = self.infra.update_state(
                {
                    "cpu_usage": 38.0,
                    "memory_usage": 54.0,
                    "disk_usage": 96.0,
                    "disk_available_gb": 2.0,
                    "filesystem": "/dev/sda1",
                    "temp_files_gb": 42.0,
                    "db_server_status": "HEALTHY",
                    "db_connected": True,
                    "services": {
                        "application-server": "HEALTHY",
                        "storage-service": "DEGRADED",
                        "payment-api": "HEALTHY",
                        "db-server": "HEALTHY",
                    },
                    "cpu_history": [34.0, 36.0, 38.0],
                }
            )
            logs = [
                "[11:00:01] WARNING storage-service Disk utilization: 85% on /dev/sda1",
                "[11:00:02] CRITICAL storage-service Disk utilization: 96% (2 GB available on /dev/sda1)",
                "[11:00:03] ERROR storage-service DISK_SPACE_CRITICAL on /dev/sda1",
                "[11:00:04] ERROR storage-service Temporary storage threshold exceeded (42 GB in /var/tmp/sim-cache)",
            ]
            return {
                "incident_type": ScenarioType.DISK_FULL.value,
                "affected_service": "storage-service",
                "initial_severity": "CRITICAL",
                "summary": "Simulated disk space exhaustion on /dev/sda1 at 96% (2 GB available).",
                "logs": logs,
                "metrics": state,
            }

        if scenario == ScenarioType.SERVICE_FAILURE:
            state = self.infra.update_state(
                {
                    "cpu_usage": 28.0,
                    "memory_usage": 62.0,
                    "disk_usage": 50.0,
                    "disk_available_gb": 50.0,
                    "temp_files_gb": 2.0,
                    "db_server_status": "UNREACHABLE",
                    "db_connected": False,
                    "services": {
                        "application-server": "HEALTHY",
                        "storage-service": "HEALTHY",
                        "payment-api": "FAILED",
                        "db-server": "UNREACHABLE",
                    },
                    "cpu_history": [29.0, 27.0, 28.0],
                }
            )
            logs = [
                "[12:00:01] ERROR payment-api unavailable (HTTP 503 Service Unavailable)",
                "[12:00:02] ERROR payment-api Connection refused while connecting to db-server:5432",
                "[12:00:03] ERROR db-server Database connection failed: connection pool exhausted",
                "[12:00:04] CRITICAL payment-api SERVICE_FAILURE healthcheck failed",
            ]
            return {
                "incident_type": ScenarioType.SERVICE_FAILURE.value,
                "affected_service": "payment-api",
                "initial_severity": "CRITICAL",
                "summary": "Simulated payment-api service failure due to refused connection to db-server.",
                "logs": logs,
                "metrics": state,
            }

        # ScenarioType.NORMAL (healthy baseline for negative evaluation testing)
        state = self.infra.reset()
        logs = [
            "[09:00:01] INFO application-server Healthcheck OK; CPU utilization: 24%",
            "[09:00:02] INFO storage-service Disk utilization: 48% on /dev/sda1",
            "[09:00:03] INFO payment-api Database connection pool healthy",
        ]
        return {
            "incident_type": ScenarioType.NORMAL.value,
            "affected_service": "application-server",
            "initial_severity": "NORMAL",
            "summary": "Simulated healthy baseline check with normal CPU, memory, disk, and services.",
            "logs": logs,
            "metrics": state,
        }

    def generate_incident(
        self,
        db: Session,
        scenario: ScenarioType,
        simulate_failure: bool = False,
    ) -> Incident:
        """Inject a simulated incident into the environment and persist initial DB records."""
        payload = self._build_scenario_payload(scenario)
        incident_id = f"INC-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:6].upper()}"
        metrics = payload["metrics"]
        affected_service = payload["affected_service"]

        incident = Incident(
            id=incident_id,
            incident_type=payload["incident_type"],
            severity=payload["initial_severity"],
            affected_service=affected_service,
            status="DETECTED" if scenario != ScenarioType.NORMAL else "NO_INCIDENT",
            summary=payload["summary"],
            is_simulated=True,
            simulate_failure=simulate_failure,
            raw_logs_json=json.dumps(payload["logs"]),
            workflow_state_json=json.dumps({"metrics_snapshot": metrics}),
        )
        db.add(incident)

        metric_row = MonitoringMetric(
            incident_id=incident_id,
            phase="BEFORE",
            cpu_usage=metrics["cpu_usage"],
            memory_usage=metrics["memory_usage"],
            disk_usage=metrics["disk_usage"],
            service_name=affected_service,
            service_status=metrics["services"].get(affected_service, "UNKNOWN"),
            db_connected=metrics["db_connected"],
            violations_json="[]",
        )
        db.add(metric_row)

        audit_row = AuditLog(
            incident_id=incident_id,
            actor="IncidentSimulator",
            event_type="INCIDENT_SIMULATED",
            what_happened=payload["summary"],
            evidence_json=json.dumps({"metrics": metrics, "log_count": len(payload["logs"])}),
            approval_required=False,
            rollback_required=False,
        )
        db.add(audit_row)
        db.commit()
        db.refresh(incident)
        return incident
