"""Incident simulation, listing, and simulated system metrics REST endpoints."""

import json
from typing import List

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from backend.agents.orchestrator import OrchestratorAgent
from backend.database.db import get_db
from backend.database.models import AgentExecution, Incident
from backend.schemas.incident import (
    IncidentDetailResponse,
    IncidentResponse,
    SimulateIncidentRequest,
    SystemMetricsResponse,
)
from backend.services.incident_simulator import IncidentSimulator, SimulatedInfrastructure

router = APIRouter(tags=["Incidents & Simulator"])


def _to_incident_response(incident: Incident) -> IncidentResponse:
    return IncidentResponse(
        id=incident.id,
        incident_type=incident.incident_type,
        severity=incident.severity,
        affected_service=incident.affected_service,
        status=incident.status,
        summary=incident.summary,
        is_simulated=incident.is_simulated,
        simulate_failure=incident.simulate_failure,
        detected_at=incident.detected_at,
        resolved_at=incident.resolved_at,
        simulated_duration_seconds=incident.simulated_duration_seconds,
    )


def _to_incident_detail(incident: Incident) -> IncidentDetailResponse:
    workflow_state = json.loads(incident.workflow_state_json or "{}")
    return IncidentDetailResponse(
        id=incident.id,
        incident_type=incident.incident_type,
        severity=incident.severity,
        affected_service=incident.affected_service,
        status=incident.status,
        summary=incident.summary,
        is_simulated=incident.is_simulated,
        simulate_failure=incident.simulate_failure,
        detected_at=incident.detected_at,
        resolved_at=incident.resolved_at,
        simulated_duration_seconds=incident.simulated_duration_seconds,
        raw_logs=json.loads(incident.raw_logs_json or "[]"),
        metrics_snapshot=workflow_state.get("metrics_snapshot", {}),
        workflow_state=workflow_state,
    )


@router.post("/incidents/simulate", response_model=IncidentDetailResponse, status_code=status.HTTP_201_CREATED)
def simulate_incident(
    payload: SimulateIncidentRequest,
    db: Session = Depends(get_db),
) -> IncidentDetailResponse:
    """Trigger a simulated IT incident scenario and store initial telemetry in SQLite."""
    simulator = IncidentSimulator()
    incident = simulator.generate_incident(
        db=db,
        scenario=payload.scenario,
        simulate_failure=payload.simulate_failure,
    )
    if payload.auto_process:
        orchestrator = OrchestratorAgent(infra=simulator.infra)
        orchestrator.process_incident(db=db, incident_id=incident.id)
        db.refresh(incident)
    return _to_incident_detail(incident)


@router.post("/incidents/{incident_id}/process")
def process_incident(incident_id: str, db: Session = Depends(get_db)):
    """Run the LangGraph multi-agent workflow for a given incident."""
    incident = db.query(Incident).filter(Incident.id == incident_id).first()
    if not incident:
        raise HTTPException(status_code=404, detail=f"Incident '{incident_id}' not found")
    orchestrator = OrchestratorAgent()
    state = orchestrator.process_incident(db=db, incident_id=incident_id)
    db.refresh(incident)
    return {
        "incident_id": incident.id,
        "status": incident.status,
        "severity": incident.severity,
        "workflow_state": state,
    }


@router.get("/incidents/{incident_id}/timeline")
def get_incident_timeline(incident_id: str, db: Session = Depends(get_db)):
    """Return chronological agent execution events stored in SQLite."""
    incident = db.query(Incident).filter(Incident.id == incident_id).first()
    if not incident:
        raise HTTPException(status_code=404, detail=f"Incident '{incident_id}' not found")
    executions = (
        db.query(AgentExecution)
        .filter(AgentExecution.incident_id == incident_id)
        .order_by(AgentExecution.executed_at.asc(), AgentExecution.id.asc())
        .all()
    )
    return {
        "incident_id": incident_id,
        "events": [
            {
                "id": ex.id,
                "timestamp": ex.executed_at.isoformat(),
                "agent_name": ex.agent_name,
                "status": ex.status,
                "message": ex.message,
                "input_summary": json.loads(ex.input_summary or "{}"),
                "output_summary": json.loads(ex.output_summary or "{}"),
            }
            for ex in executions
        ],
    }


@router.get("/incidents", response_model=List[IncidentResponse])
def list_incidents(db: Session = Depends(get_db)) -> List[IncidentResponse]:
    """List all recorded incidents ordered by newest first."""
    incidents = db.query(Incident).order_by(Incident.detected_at.desc()).all()
    return [_to_incident_response(inc) for inc in incidents]


@router.get("/incidents/{incident_id}", response_model=IncidentDetailResponse)
def get_incident(incident_id: str, db: Session = Depends(get_db)) -> IncidentDetailResponse:
    """Fetch full details for a single incident."""
    incident = db.query(Incident).filter(Incident.id == incident_id).first()
    if not incident:
        raise HTTPException(status_code=404, detail=f"Incident '{incident_id}' not found")
    return _to_incident_detail(incident)


@router.get("/system/metrics", response_model=SystemMetricsResponse)
def get_system_metrics() -> SystemMetricsResponse:
    """Return current state of the simulated IT infrastructure."""
    infra = SimulatedInfrastructure()
    state = infra.get_system_metrics()
    return SystemMetricsResponse(
        cpu_usage=state["cpu_usage"],
        memory_usage=state["memory_usage"],
        disk_usage=state["disk_usage"],
        disk_available_gb=state["disk_available_gb"],
        filesystem=state["filesystem"],
        temp_files_gb=state["temp_files_gb"],
        db_server_status=state["db_server_status"],
        db_connected=state["db_connected"],
        services=state["services"],
        cpu_history=state["cpu_history"],
        updated_at=state["updated_at"],
        is_simulated=state.get("is_simulated", True),
    )


@router.post("/system/reset", response_model=SystemMetricsResponse)
def reset_system_metrics() -> SystemMetricsResponse:
    """Reset simulated infrastructure back to healthy baseline."""
    infra = SimulatedInfrastructure()
    state = infra.reset()
    return SystemMetricsResponse(
        cpu_usage=state["cpu_usage"],
        memory_usage=state["memory_usage"],
        disk_usage=state["disk_usage"],
        disk_available_gb=state["disk_available_gb"],
        filesystem=state["filesystem"],
        temp_files_gb=state["temp_files_gb"],
        db_server_status=state["db_server_status"],
        db_connected=state["db_connected"],
        services=state["services"],
        cpu_history=state["cpu_history"],
        updated_at=state["updated_at"],
        is_simulated=state.get("is_simulated", True),
    )
