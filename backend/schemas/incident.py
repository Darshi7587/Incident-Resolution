"""Pydantic schemas for incidents, simulation requests, and system metrics."""

from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class ScenarioType(str, Enum):
    """Supported incident simulation scenarios."""

    HIGH_CPU = "high_cpu"
    DISK_FULL = "disk_full"
    SERVICE_FAILURE = "service_failure"
    NORMAL = "normal"


class SimulateIncidentRequest(BaseModel):
    """Request payload for triggering a simulated IT incident."""

    scenario: ScenarioType = Field(..., description="Scenario type to simulate")
    simulate_failure: bool = Field(
        default=False,
        description="Optional flag to simulate remediation failure for rollback/escalation testing",
    )
    auto_process: bool = Field(
        default=False,
        description="Whether to immediately trigger LangGraph processing after creation",
    )


class SystemMetricsResponse(BaseModel):
    """Current state of the simulated IT infrastructure."""

    cpu_usage: float
    memory_usage: float
    disk_usage: float
    disk_available_gb: float
    filesystem: str
    temp_files_gb: float
    db_server_status: str
    db_connected: bool
    services: Dict[str, str]
    cpu_history: List[float]
    updated_at: str
    is_simulated: bool = True


class IncidentResponse(BaseModel):
    """Summary representation of an incident."""

    id: str
    incident_type: str
    severity: str
    affected_service: str
    status: str
    summary: str
    is_simulated: bool
    simulate_failure: bool
    detected_at: datetime
    resolved_at: Optional[datetime] = None
    simulated_duration_seconds: Optional[float] = None


class IncidentDetailResponse(IncidentResponse):
    """Detailed representation of an incident including logs and workflow state."""

    raw_logs: List[str] = Field(default_factory=list)
    metrics_snapshot: Dict[str, Any] = Field(default_factory=dict)
    workflow_state: Dict[str, Any] = Field(default_factory=dict)
