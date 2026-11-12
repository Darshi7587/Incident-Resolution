"""Phase 2 tests: Incident simulator scenarios, simulated infrastructure, and REST endpoints."""

import asyncio
import httpx

from backend.config import get_settings
from backend.database.db import init_db, reset_engine
from backend.main import create_app
from backend.services.incident_simulator import SimulatedInfrastructure


def _setup_test_env(tmp_path, monkeypatch):
    db_file = tmp_path / "phase2_test.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_file.as_posix()}")
    get_settings.cache_clear()
    reset_engine()
    init_db()
    return create_app()


def test_simulated_infrastructure_state_and_health(tmp_path):
    """Verify SimulatedInfrastructure maintains metrics, services, and resets cleanly."""
    infra = SimulatedInfrastructure(state_file=tmp_path / "sim_state.json")
    baseline = infra.get_system_metrics()
    assert baseline["cpu_usage"] == 24.0
    assert baseline["services"]["payment-api"] == "HEALTHY"
    assert infra.check_service_health("payment-api")["healthy"] is True

    infra.update_state({"cpu_usage": 95.0, "services": {"application-server": "DEGRADED"}})
    health = infra.check_service_health("application-server")
    assert health["healthy"] is False
    assert health["cpu_usage"] == 95.0

    reset_state = infra.reset()
    assert reset_state["cpu_usage"] == 24.0
    assert reset_state["services"]["application-server"] == "HEALTHY"


def test_simulate_all_three_scenarios_via_api(tmp_path, monkeypatch):
    """Verify POST /incidents/simulate, GET /incidents, and GET /system/metrics for all scenarios."""
    app = _setup_test_env(tmp_path, monkeypatch)

    async def _run():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            # 1. High CPU
            r1 = await client.post("/incidents/simulate", json={"scenario": "high_cpu"})
            assert r1.status_code == 201
            inc1 = r1.json()
            assert inc1["incident_type"] == "high_cpu"
            assert inc1["affected_service"] == "application-server"
            assert inc1["metrics_snapshot"]["cpu_usage"] == 95.0
            assert len(inc1["raw_logs"]) == 5

            # 2. Disk Full
            r2 = await client.post("/incidents/simulate", json={"scenario": "disk_full"})
            assert r2.status_code == 201
            inc2 = r2.json()
            assert inc2["incident_type"] == "disk_full"
            assert inc2["affected_service"] == "storage-service"
            assert inc2["metrics_snapshot"]["disk_usage"] == 96.0
            assert inc2["metrics_snapshot"]["disk_available_gb"] == 2.0

            # 3. Service Failure
            r3 = await client.post("/incidents/simulate", json={"scenario": "service_failure"})
            assert r3.status_code == 201
            inc3 = r3.json()
            assert inc3["incident_type"] == "service_failure"
            assert inc3["affected_service"] == "payment-api"
            assert inc3["metrics_snapshot"]["db_connected"] is False
            assert inc3["metrics_snapshot"]["services"]["payment-api"] == "FAILED"

            # Verify listing and detail lookup
            r_list = await client.get("/incidents")
            assert r_list.status_code == 200
            assert len(r_list.json()) == 3

            r_detail = await client.get(f"/incidents/{inc1['id']}")
            assert r_detail.status_code == 200
            assert r_detail.json()["id"] == inc1["id"]

            # Verify system metrics and reset
            r_metrics = await client.get("/system/metrics")
            assert r_metrics.status_code == 200
            assert r_metrics.json()["services"]["payment-api"] == "FAILED"

            r_reset = await client.post("/system/reset")
            assert r_reset.status_code == 200
            assert r_reset.json()["services"]["payment-api"] == "HEALTHY"

    asyncio.run(_run())
    reset_engine()
    get_settings.cache_clear()
