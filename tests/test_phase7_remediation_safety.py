"""Phase 7 tests: Remediation Planning, Risk Engine, Allowlist, Human Approval, and Rollback."""

import pytest

from backend.agents.orchestrator import OrchestratorAgent
from backend.config import get_settings
from backend.database.db import get_session_factory, init_db, reset_engine
from backend.database.models import ApprovalRequest, RemediationAction
from backend.rag.ingest import ingest_runbooks
from backend.schemas.incident import ScenarioType
from backend.services.incident_simulator import IncidentSimulator, SimulatedInfrastructure
from backend.services.remediation_executor import RemediationExecutor, UnsafeActionError
from backend.services.risk_engine import RiskEngine


def test_risk_engine_and_executor_safety_guards(tmp_path):
    """Verify RiskEngine allowlist, risk tiers, UnsafeActionError, and rollback."""
    settings = get_settings()
    risk = RiskEngine(settings=settings)

    low_eval = risk.evaluate("cleanup_simulated_temp_files", "storage-service")
    assert low_eval["allowed"] is True
    assert low_eval["risk_level"] == "LOW"
    assert low_eval["requires_approval"] is False

    med_eval = risk.evaluate("restart_simulated_service", "application-server")
    assert med_eval["allowed"] is True
    assert med_eval["risk_level"] == "MEDIUM"
    assert med_eval["requires_approval"] is True

    high_eval = risk.evaluate("restore_simulated_service", "payment-api")
    assert high_eval["allowed"] is True
    assert high_eval["risk_level"] == "HIGH"
    assert high_eval["requires_approval"] is True

    bad_eval = risk.evaluate("rm_rf_root_shell", "application-server")
    assert bad_eval["allowed"] is False
    assert bad_eval["requires_approval"] is True

    infra = SimulatedInfrastructure(state_file=tmp_path / "sim_state.json")
    infra.update_state({"cpu_usage": 95.0, "services": {"application-server": "DEGRADED"}})
    executor = RemediationExecutor(infra=infra)

    with pytest.raises(UnsafeActionError):
        executor.execute_action("rm_rf_root_shell", "application-server", "APPROVED")

    with pytest.raises(UnsafeActionError):
        executor.execute_action("restart_simulated_service", "application-server", "PENDING")

    with pytest.raises(UnsafeActionError):
        executor.execute_action("restart_simulated_service", "application-server", "REJECTED")

    # Simulate failure + controlled rollback
    fail_res = executor.execute_action(
        "restart_simulated_service",
        "application-server",
        "APPROVED",
        simulate_failure=True,
    )
    assert fail_res["action_succeeded"] is False
    assert infra.get_system_metrics()["services"]["application-server"] == "FAILED"

    rb = executor.rollback_simulated_action(fail_res["before_state"])
    assert rb["rolled_back"] is True
    assert infra.get_system_metrics()["cpu_usage"] == 95.0
    assert infra.get_system_metrics()["services"]["application-server"] == "DEGRADED"


def test_persistent_approval_approve_and_reject_workflows(tmp_path, monkeypatch):
    """Verify LOW auto-executes, HIGH pauses for approval, approve executes, reject blocks execution."""
    db_file = tmp_path / "phase7_safety.db"
    chroma_dir = tmp_path / "chroma_p7"
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
        # 1. Disk Full (LOW risk) -> auto-approved and executed immediately
        inc_disk = sim.generate_incident(db=db, scenario=ScenarioType.DISK_FULL)
        state_disk = orch.process_incident(db=db, incident_id=inc_disk.id)
        assert state_disk["workflow_status"] == "EXECUTED"
        assert state_disk["remediation_plan"]["risk_level"] == "LOW"
        assert infra.get_system_metrics()["disk_usage"] == 54.0

        # 2. Service Failure (HIGH risk) -> pauses at AWAITING_APPROVAL, then REJECTED
        inc_svc = sim.generate_incident(db=db, scenario=ScenarioType.SERVICE_FAILURE)
        state_svc = orch.process_incident(db=db, incident_id=inc_svc.id)
        assert state_svc["workflow_status"] == "AWAITING_APPROVAL"
        approval_id = state_svc["remediation_plan"]["approval_id"]
        assert infra.get_system_metrics()["services"]["payment-api"] == "FAILED"

        rej_res = orch.reject_and_escalate(db=db, approval_id=approval_id, decided_by="sre-lead", comment="Hold for DBA")
        assert rej_res["incident"].status == "ESCALATED"
        assert rej_res["approval"].status == "REJECTED"
        # Must NOT have executed!
        assert infra.get_system_metrics()["services"]["payment-api"] == "FAILED"
        act_row = db.query(RemediationAction).filter_by(incident_id=inc_svc.id).first()
        assert act_row.execution_status == "REJECTED_NOT_EXECUTED"

        # 3. High CPU (MEDIUM risk) -> pauses at AWAITING_APPROVAL, then APPROVED & executed
        inc_cpu = sim.generate_incident(db=db, scenario=ScenarioType.HIGH_CPU)
        state_cpu = orch.process_incident(db=db, incident_id=inc_cpu.id)
        assert state_cpu["workflow_status"] == "AWAITING_APPROVAL"
        cpu_approval_id = state_cpu["remediation_plan"]["approval_id"]
        assert infra.get_system_metrics()["cpu_usage"] == 95.0

        app_res = orch.approve_and_resume(db=db, approval_id=cpu_approval_id, decided_by="oncall-eng", comment="Approved restart")
        assert app_res["approval"].status == "APPROVED"
        assert app_res["incident"].status == "EXECUTED"
        assert infra.get_system_metrics()["cpu_usage"] == 26.0
        assert infra.get_system_metrics()["services"]["application-server"] == "HEALTHY"

        # Verify idempotency: cannot approve the same approval request twice
        with pytest.raises(ValueError):
            orch.approve_and_resume(db=db, approval_id=cpu_approval_id, decided_by="oncall-eng")

        assert db.query(ApprovalRequest).count() == 2

    reset_engine()
    get_settings.cache_clear()
