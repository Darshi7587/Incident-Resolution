"""Phase 8 tests: Validation Agent, Rollback on Failure, Audit Report, and Evaluation Metrics."""

from backend.agents.orchestrator import OrchestratorAgent
from backend.config import get_settings
from backend.database.db import get_session_factory, init_db, reset_engine
from backend.database.models import AuditLog, MonitoringMetric, ValidationResult
from backend.rag.ingest import ingest_runbooks
from backend.schemas.incident import ScenarioType
from backend.services.audit_service import build_incident_report, render_report_text
from backend.services.evaluation_service import run_evaluation
from backend.services.incident_simulator import IncidentSimulator, SimulatedInfrastructure


def test_validation_rollback_and_audit_report(tmp_path, monkeypatch):
    """Verify recovery validation, failed-remediation rollback, and complete audit report generation."""
    db_file = tmp_path / "phase8_val.db"
    chroma_dir = tmp_path / "chroma_p8"
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
        # 1. Successful Service Failure resolution -> RESOLVED + Report
        inc_ok = sim.generate_incident(db=db, scenario=ScenarioType.SERVICE_FAILURE, simulate_failure=False)
        state_ok = orch.process_incident(db=db, incident_id=inc_ok.id)
        assert state_ok["workflow_status"] == "AWAITING_APPROVAL"
        ap_id = state_ok["remediation_plan"]["approval_id"]

        res_ok = orch.approve_and_resume(db=db, approval_id=ap_id, decided_by="qa-lead", comment="Proceed")
        assert res_ok["incident"].status == "RESOLVED"
        assert res_ok["incident"].resolved_at is not None
        assert res_ok["incident"].simulated_duration_seconds is not None

        metrics_rows = db.query(MonitoringMetric).filter_by(incident_id=inc_ok.id).all()
        phases = {m.phase for m in metrics_rows}
        assert phases == {"BEFORE", "AFTER"}

        report = build_incident_report(db=db, incident_id=inc_ok.id)
        assert report is not None
        assert report["incident_summary"]["status"] == "RESOLVED"
        assert report["before_and_after_metrics"]["before"]["db_connected"] is False
        assert report["before_and_after_metrics"]["after"]["db_connected"] is True
        assert report["validation_outcome"]["is_recovered"] is True
        assert len(report["audit_events"]) >= 5

        txt = render_report_text(report)
        assert "AUTONOMOUS IT INCIDENT RESOLUTION REPORT" in txt
        assert "service_failure.md" in txt

        # 2. Failed remediation (simulate_failure=True) -> rollback triggered & NOT RESOLVED
        inc_fail = sim.generate_incident(db=db, scenario=ScenarioType.HIGH_CPU, simulate_failure=True)
        state_fail = orch.process_incident(db=db, incident_id=inc_fail.id)
        ap_fail_id = state_fail["remediation_plan"]["approval_id"]
        res_fail = orch.approve_and_resume(db=db, approval_id=ap_fail_id, decided_by="qa-lead")

        assert res_fail["incident"].status == "ESCALATED"
        assert res_fail["incident"].status != "RESOLVED"
        val_row = db.query(ValidationResult).filter_by(incident_id=inc_fail.id).first()
        assert val_row.is_recovered is False
        assert val_row.rollback_triggered is True
        assert val_row.rollback_status == "ROLLED_BACK"
        # Rolled back CPU to pre-remediation snapshot (95%) and service DEGRADED
        assert infra.get_system_metrics()["cpu_usage"] == 95.0
        assert db.query(AuditLog).filter_by(incident_id=inc_fail.id, event_type="REMEDIATION_ROLLED_BACK").count() == 1

    reset_engine()
    get_settings.cache_clear()


def test_evaluation_dataset_execution(monkeypatch):
    """Verify real simulated evaluation pipeline executes all cases and computes metrics."""
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://127.0.0.1:19999")
    get_settings.cache_clear()
    report = run_evaluation(settings=get_settings())
    assert report["is_simulated"] is True
    assert report["total_cases"] == 7
    assert report["passed_cases"] == 7
    metrics = report["metrics"]
    assert metrics["incident_detection_accuracy"] == 1.0
    assert metrics["root_cause_identification_accuracy"] == 1.0
    assert metrics["runbook_retrieval_relevance"] == 1.0
    assert metrics["successful_remediation_rate"] == 1.0
    assert metrics["human_approval_compliance"] == 1.0
    assert metrics["unsafe_action_prevention"] == 1.0
    get_settings.cache_clear()
