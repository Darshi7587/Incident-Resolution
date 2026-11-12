"""Phase 1 tests: SQLite database initialization and FastAPI /health endpoint."""

import asyncio
import httpx
from sqlalchemy import inspect

from backend.config import get_settings
from backend.database.db import get_engine, init_db, reset_engine
from backend.main import create_app


def test_sqlite_tables_created(tmp_path, monkeypatch):
    """Verify all 9 required SQLite tables are created on init_db()."""
    db_file = tmp_path / "test_incidents.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_file.as_posix()}")
    get_settings.cache_clear()
    reset_engine()

    init_db()
    inspector = inspect(get_engine())
    tables = set(inspector.get_table_names())

    expected_tables = {
        "incidents",
        "agent_executions",
        "monitoring_metrics",
        "root_cause_analysis",
        "retrieved_runbooks",
        "remediation_actions",
        "approval_requests",
        "validation_results",
        "audit_logs",
    }
    assert expected_tables.issubset(tables)

    reset_engine()
    get_settings.cache_clear()


def test_health_endpoint(tmp_path, monkeypatch):
    """Verify GET /health returns 200 OK and reports healthy database status."""
    db_file = tmp_path / "health_test.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_file.as_posix()}")
    get_settings.cache_clear()
    reset_engine()

    init_db()
    app = create_app()

    async def _call():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            return await client.get("/health")

    response = asyncio.run(_call())
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "healthy"
    assert payload["database_connected"] is True
    assert payload["app_name"] == "Autonomous IT Incident Resolution"
    assert payload["thresholds"]["cpu_critical"] == 90.0

    reset_engine()
    get_settings.cache_clear()
