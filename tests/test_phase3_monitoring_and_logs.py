"""Phase 3 tests: Monitoring Agent threshold detection and Log Analysis Agent classification."""

from backend.agents.log_agent import LogAnalysisAgent
from backend.agents.monitoring_agent import MonitoringAgent
from backend.config import get_settings
from backend.database.db import get_session_factory, init_db, reset_engine
from backend.database.models import AgentExecution, AuditLog, MonitoringMetric
from backend.schemas.incident import ScenarioType
from backend.services.incident_simulator import IncidentSimulator, SimulatedInfrastructure


def test_monitoring_agent_thresholds(tmp_path, monkeypatch):
    """Verify MonitoringAgent classifies NORMAL, WARNING, and CRITICAL thresholds accurately."""
    db_file = tmp_path / "phase3_mon.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_file.as_posix()}")
    get_settings.cache_clear()
    reset_engine()
    init_db()

    infra = SimulatedInfrastructure(state_file=tmp_path / "sim_state.json")
    agent = MonitoringAgent(settings=get_settings(), infra=infra)

    # Normal baseline
    normal_res = agent.analyze(metrics=infra.get_system_metrics())
    assert normal_res["severity"] == "NORMAL"
    assert normal_res["anomaly_detected"] is False
    assert normal_res["threshold_violations"] == []

    # Warning CPU (72%)
    warn_metrics = infra.update_state({"cpu_usage": 72.0})
    warn_res = agent.analyze(metrics=warn_metrics)
    assert warn_res["severity"] == "WARNING"
    assert warn_res["anomaly_detected"] is True
    assert warn_res["threshold_violations"][0]["level"] == "WARNING"

    # Critical CPU (95%) + DB persistence
    SessionLocal = get_session_factory()
    with SessionLocal() as db:
        sim = IncidentSimulator(infra=infra)
        inc = sim.generate_incident(db=db, scenario=ScenarioType.HIGH_CPU)
        crit_res = agent.analyze(incident_id=inc.id, db=db)

        assert crit_res["severity"] == "CRITICAL"
        assert "application-server" in crit_res["affected_services"]
        assert db.query(AgentExecution).filter_by(incident_id=inc.id, agent_name="Monitoring Agent").count() == 1
        metric_row = db.query(MonitoringMetric).filter_by(incident_id=inc.id).first()
        assert "cpu_usage" in metric_row.violations_json

    reset_engine()
    get_settings.cache_clear()


def test_log_analysis_agent_parses_and_correlates(tmp_path, monkeypatch):
    """Verify LogAnalysisAgent parses timestamps/levels/services and extracts error signatures."""
    db_file = tmp_path / "phase3_logs.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_file.as_posix()}")
    get_settings.cache_clear()
    reset_engine()
    init_db()

    infra = SimulatedInfrastructure(state_file=tmp_path / "sim_state.json")
    SessionLocal = get_session_factory()
    with SessionLocal() as db:
        sim = IncidentSimulator(infra=infra)
        inc = sim.generate_incident(db=db, scenario=ScenarioType.SERVICE_FAILURE)

        log_agent = LogAnalysisAgent()
        logs = [
            "[12:00:01] ERROR payment-api unavailable (HTTP 503 Service Unavailable)",
            "[12:00:02] ERROR payment-api Connection refused while connecting to db-server:5432",
            "[12:00:03] ERROR db-server Database connection failed: connection pool exhausted",
            "[12:00:04] CRITICAL payment-api SERVICE_FAILURE healthcheck failed",
        ]
        report = log_agent.analyze(logs=logs, affected_service="payment-api", incident_id=inc.id, db=db)

        assert report["total_logs_processed"] == 4
        assert report["counts_by_level"]["CRITICAL"] == 1
        assert report["counts_by_level"]["ERROR"] == 3
        assert "SERVICE_FAILURE" in report["error_signatures"]
        assert "DB_CONNECTION_REFUSED" in report["error_signatures"]
        assert "payment-api" in report["correlated_services"]
        assert "db-server" in report["correlated_services"]
        assert db.query(AgentExecution).filter_by(incident_id=inc.id, agent_name="Log Analysis Agent").count() == 1
        assert db.query(AuditLog).filter_by(incident_id=inc.id, event_type="LOGS_ANALYZED").count() == 1

    reset_engine()
    get_settings.cache_clear()
