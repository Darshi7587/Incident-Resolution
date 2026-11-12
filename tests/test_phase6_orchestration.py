"""Phase 6 tests: LangGraph StateGraph orchestration, routing, and timeline tracking."""

import asyncio
import httpx

from backend.agents.orchestrator import OrchestratorAgent
from backend.config import get_settings
from backend.database.db import get_session_factory, init_db, reset_engine
from backend.main import create_app
from backend.rag.ingest import ingest_runbooks
from backend.schemas.incident import ScenarioType
from backend.services.incident_simulator import IncidentSimulator, SimulatedInfrastructure


def test_orchestrator_langgraph_routes_and_timeline(tmp_path, monkeypatch):
    """Verify LangGraph workflow investigates incidents, skips normal baseline, and escalates missing runbooks."""
    db_file = tmp_path / "phase6_orch.db"
    chroma_dir = tmp_path / "chroma_p6"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_file.as_posix()}")
    monkeypatch.setenv("CHROMA_PERSIST_DIR", str(chroma_dir))
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://127.0.0.1:19999")
    get_settings.cache_clear()
    reset_engine()
    init_db()

    settings = get_settings()
    ingest_runbooks(settings=settings, force_reingest=True)

    infra = SimulatedInfrastructure(state_file=tmp_path / "sim_state.json")
    sim = IncidentSimulator(infra=infra)
    orch = OrchestratorAgent(settings=settings, infra=infra)

    SessionLocal = get_session_factory()
    with SessionLocal() as db:
        # 1. High CPU full investigation -> pauses at remediation approval gate
        inc_cpu = sim.generate_incident(db=db, scenario=ScenarioType.HIGH_CPU)
        state_cpu = orch.process_incident(db=db, incident_id=inc_cpu.id)
        assert state_cpu["workflow_status"] == "AWAITING_APPROVAL"
        assert state_cpu["monitoring_result"]["severity"] == "CRITICAL"
        assert state_cpu["rag_result"]["primary_runbook"] == "cpu_high.md"

        # 2. Normal baseline -> early exit NO_INCIDENT
        inc_norm = sim.generate_incident(db=db, scenario=ScenarioType.NORMAL)
        state_norm = orch.process_incident(db=db, incident_id=inc_norm.id)
        assert state_norm["workflow_status"] == "NO_INCIDENT"
        assert "rca_result" not in state_norm

        # 3. Missing runbook evidence -> ESCALATED
        inc_disk = sim.generate_incident(db=db, scenario=ScenarioType.DISK_FULL)
        state_esc = orch.process_incident(db=db, incident_id=inc_disk.id, rag_min_relevance=0.99)
        assert state_esc["workflow_status"] == "ESCALATED"
        assert "No matching runbook evidence" in state_esc["escalation_reason"]

    # 4. Verify REST /process and /timeline endpoints
    app = create_app()

    async def _api_flow():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            r_sim = await client.post("/incidents/simulate", json={"scenario": "service_failure"})
            assert r_sim.status_code == 201
            inc_id = r_sim.json()["id"]

            r_proc = await client.post(f"/incidents/{inc_id}/process")
            assert r_proc.status_code == 200
            proc_data = r_proc.json()
            assert proc_data["status"] == "AWAITING_APPROVAL"
            assert proc_data["workflow_state"]["rag_result"]["primary_runbook"] == "service_failure.md"

            r_time = await client.get(f"/incidents/{inc_id}/timeline")
            assert r_time.status_code == 200
            events = r_time.json()["events"]
            agents_seen = [e["agent_name"] for e in events]
            assert "Orchestrator Agent" in agents_seen
            assert "Monitoring Agent" in agents_seen
            assert "Log Analysis Agent" in agents_seen
            assert "Root Cause Analysis Agent" in agents_seen
            assert "RAG Knowledge Agent" in agents_seen

            await client.post("/system/reset")

    asyncio.run(_api_flow())
    reset_engine()
    get_settings.cache_clear()
