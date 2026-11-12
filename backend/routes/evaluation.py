"""Evaluation API endpoints for running and retrieving simulated benchmark metrics."""

from typing import Any, Dict

from fastapi import APIRouter

from backend.config import get_settings
from backend.services.evaluation_service import get_latest_evaluation, run_evaluation

router = APIRouter(prefix="/evaluation", tags=["Evaluation"])


@router.post("/run")
def trigger_evaluation() -> Dict[str, Any]:
    """Execute the simulated evaluation dataset and calculate performance/safety metrics."""
    return run_evaluation(settings=get_settings())


@router.get("/latest")
def latest_evaluation() -> Dict[str, Any]:
    """Retrieve the latest computed evaluation metrics."""
    return get_latest_evaluation()
