"""Agent 1: Orchestrator Agent — coordinates multi-agent execution via LangGraph."""

from __future__ import annotations

import json
from typing import Any, Dict, Optional

from sqlalchemy.orm import Session

from backend.config import Settings, get_settings
from backend.database.models import AgentExecution, AuditLog, Incident
from backend.services.incident_simulator import SimulatedInfrastructure
from backend.workflows.incident_workflow import IncidentState, build_investigation_graph


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

        graph = build_investigation_graph(
            db=db,
            settings=self.settings,
            infra=self.infra,
            rag_min_relevance=rag_min_relevance,
        )
        final_state = graph.invoke(initial_state)

        final_status = final_state.get("workflow_status", "INVESTIGATED")
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
