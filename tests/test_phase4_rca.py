"""Phase 4 tests: Root Cause Analysis Agent (Ollama integration + deterministic fallback)."""

from backend.agents.log_agent import LogAnalysisAgent
from backend.agents.monitoring_agent import MonitoringAgent
from backend.agents.root_cause_agent import RootCauseAnalysisAgent
from backend.config import get_settings
from backend.database.db import get_session_factory, init_db, reset_engine
from backend.database.models import RootCauseAnalysis
from backend.schemas.incident import ScenarioType
from backend.services.incident_simulator import IncidentSimulator, SimulatedInfrastructure


def test_rca_deterministic_fallback_all_scenarios(tmp_path, monkeypatch):
    """Verify distinct probable root causes and confidence scores across all 3 scenarios + normal."""
    db_file = tmp_path / "phase4_rca.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_file.as_posix()}")
    # Point Ollama to an unused local port to test deterministic fallback reliably
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://127.0.0.1:19999")
    get_settings.cache_clear()
    reset_engine()
    init_db()

    infra = SimulatedInfrastructure(state_file=tmp_path / "sim_state.json")
    sim = IncidentSimulator(infra=infra)
    mon = MonitoringAgent(settings=get_settings(), infra=infra)
    log_agent = LogAnalysisAgent()
    rca_agent = RootCauseAnalysisAgent(settings=get_settings())

    SessionLocal = get_session_factory()
    with SessionLocal() as db:
        # 1. High CPU
        inc_cpu = sim.generate_incident(db=db, scenario=ScenarioType.HIGH_CPU)
        mon_cpu = mon.analyze(incident_id=inc_cpu.id, db=db)
        log_cpu = log_agent.analyze(
            logs=["[10:00:03] CRITICAL application-server CPU utilization: 95%", "[10:00:04] ERROR application-server CPU_THRESHOLD_EXCEEDED"],
            affected_service="application-server",
            incident_id=inc_cpu.id,
            db=db,
        )
        rca_cpu = rca_agent.analyze(mon_cpu, log_cpu, "high_cpu", incident_id=inc_cpu.id, db=db)
        assert rca_cpu["reasoning_source"] == "DETERMINISTIC_FALLBACK"
        assert "cpu" in rca_cpu["probable_cause"].lower() or "thread" in rca_cpu["probable_cause"].lower()
        assert rca_cpu["confidence_score"] >= 0.8

        # 2. Disk Full
        inc_disk = sim.generate_incident(db=db, scenario=ScenarioType.DISK_FULL)
        mon_disk = mon.analyze(incident_id=inc_disk.id, db=db)
        log_disk = log_agent.analyze(
            logs=["[11:00:02] CRITICAL storage-service Disk utilization: 96%", "[11:00:03] ERROR storage-service DISK_SPACE_CRITICAL"],
            affected_service="storage-service",
            incident_id=inc_disk.id,
            db=db,
        )
        rca_disk = rca_agent.analyze(mon_disk, log_disk, "disk_full", incident_id=inc_disk.id, db=db)
        assert rca_disk["reasoning_source"] == "DETERMINISTIC_FALLBACK"
        assert "temporary file" in rca_disk["probable_cause"].lower() or "filesystem" in rca_disk["probable_cause"].lower()

        # 3. Service Failure
        inc_svc = sim.generate_incident(db=db, scenario=ScenarioType.SERVICE_FAILURE)
        mon_svc = mon.analyze(incident_id=inc_svc.id, db=db)
        log_svc = log_agent.analyze(
            logs=["[12:00:02] ERROR payment-api Connection refused", "[12:00:04] CRITICAL payment-api SERVICE_FAILURE"],
            affected_service="payment-api",
            incident_id=inc_svc.id,
            db=db,
        )
        rca_svc = rca_agent.analyze(mon_svc, log_svc, "service_failure", incident_id=inc_svc.id, db=db)
        assert rca_svc["reasoning_source"] == "DETERMINISTIC_FALLBACK"
        assert "database" in rca_svc["probable_cause"].lower()

        # Ensure all 3 hypotheses are distinct and persisted
        assert len({rca_cpu["probable_cause"], rca_disk["probable_cause"], rca_svc["probable_cause"]}) == 3
        assert db.query(RootCauseAnalysis).count() == 3

    reset_engine()
    get_settings.cache_clear()


def test_rca_ollama_path_with_mock(monkeypatch):
    """Verify Ollama LLM response parsing when Ollama returns structured JSON."""
    get_settings.cache_clear()
    agent = RootCauseAnalysisAgent(settings=get_settings())

    class _FakeResp:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "response": '{"probable_cause": "Probable worker thread deadlock on application-server", "confidence_score": 0.91, "reasoning_summary": "CPU hit 95% with CPU_THRESHOLD_EXCEEDED.", "supporting_evidence": ["CPU 95%"], "hypotheses": []}'
            }

    class _FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def post(self, url, json):
            return _FakeResp()

    monkeypatch.setattr("backend.agents.root_cause_agent.httpx.Client", _FakeClient)
    res = agent.analyze(
        monitoring_result={"severity": "CRITICAL", "metrics": {"cpu_usage": 95.0}},
        log_result={"error_signatures": ["CPU_THRESHOLD_EXCEEDED"], "related_events": []},
        incident_type="high_cpu",
        prefer_llm=True,
    )
    assert res["reasoning_source"] == "OLLAMA_LLM"
    assert res["confidence_score"] == 0.91
    assert "deadlock" in res["probable_cause"].lower()
    get_settings.cache_clear()
