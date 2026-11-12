"""Shared Pydantic schemas for API health and configuration responses."""

from typing import Dict
from pydantic import BaseModel


class HealthResponse(BaseModel):
    """Response model for GET /health."""

    status: str
    app_name: str
    environment: str
    database_connected: bool
    ollama_base_url: str
    ollama_model: str
    thresholds: Dict[str, float]
