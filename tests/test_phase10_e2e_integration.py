"""Phase 10 tests: Full end-to-end REST API, SQLite persistence, safety, and rollback integration."""

import asyncio
import httpx

from backend.config import get_settings
from backend.database.db import init_db, reset_engine
from backend.main import create_app
from backend.rag.ingest import ingest_runbooks


def test_full_end_to_end_api_and_persistence(tmp_path, monkeypatch):
    """Verify all Phase 1 acceptance criteria end-to-end through FastAPI REST endpoints."""
    db_file = tmp_path / "phase10_e2e.db"
    chroma_dir = tmp_path / "chroma_p10"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_file.as_posix()}")
    monkeypatch.setenv("CHROMA_PERSIST_DIR", str(chroma_dir))
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://127.0.0.1:19999")
    get_settings.cache_clear()
    reset_engine()
    init_db()
    ingest_runbooks(settings=get_settings(), force_reingest=True)

    app = create_app()

    async def _run_e2e():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            # 0. Health and Runbooks endpoints
            assert (await client.get("/health")).status_code == 200
            rb_resp = await client.get("/runbooks")
            assert rb_resp.status_code == 200
            assert rb_resp.json()["count"] == 3

            # 1. Scenario 1: High CPU -> Medium risk -> Pending Approval -> Approve -> RESOLVED
            r_cpu = await client.post("/incidents/simulate", json={"scenario": "high_cpu", "auto_process": True})
            assert r_cpu.status_code == 201
            cpu_inc = r_cpu.json()
            assert cpu_inc["status"] == "AWAITING_APPROVAL"
            cpu_approval_id = cpu_inc["workflow_state"]["remediation_plan"]["approval_id"]

            pending = (await client.get("/approvals/pending")).json()
            assert any(p["id"] == cpu_approval_id for p in pending)

            r_app = await client.post(
                f"/approvals/{cpu_approval_id}/approve",
                json={"decided_by": "capstone-reviewer", "comment": "Verified safe restart"},
            )
            assert r_app.status_code == 200
            assert r_app.json()["incident_status"] == "RESOLVED"
            assert r_app.json()["executed"] is True

            rep_cpu = (await client.get(f"/incidents/{cpu_inc['id']}/report")).json()
            assert rep_cpu["before_and_after_metrics"]["before"]["cpu_usage"] == 95.0
            assert rep_cpu["before_and_after_metrics"]["after"]["cpu_usage"] == 26.0
            assert rep_cpu["retrieved_runbooks"][0]["runbook_name"] == "cpu_high.md"

            # 2. Scenario 2: Disk Full -> Low risk -> Auto-approved -> RESOLVED
            r_disk = await client.post("/incidents/simulate", json={"scenario": "disk_full", "auto_process": True})
            assert r_disk.status_code == 201
            disk_inc = r_disk.json()
            assert disk_inc["status"] == "RESOLVED"
            rep_disk = (await client.get(f"/incidents/{disk_inc['id']}/report")).json()
            assert rep_disk["before_and_after_metrics"]["before"]["disk_usage"] == 96.0
            assert rep_disk["before_and_after_metrics"]["after"]["disk_usage"] == 54.0
            assert rep_disk["retrieved_runbooks"][0]["runbook_name"] == "disk_full.md"

            # 3a. Scenario 3: Service Failure -> High risk -> Reject -> NOT executed & ESCALATED
            r_svc_rej = await client.post("/incidents/simulate", json={"scenario": "service_failure", "auto_process": True})
            assert r_svc_rej.status_code == 201
            svc_rej_inc = r_svc_rej.json()
            assert svc_rej_inc["status"] == "AWAITING_APPROVAL"
            rej_apr_id = svc_rej_inc["workflow_state"]["remediation_plan"]["approval_id"]

            r_rej = await client.post(
                f"/approvals/{rej_apr_id}/reject",
                json={"decided_by": "capstone-reviewer", "comment": "Escalate to DBA"},
            )
            assert r_rej.status_code == 200
            assert r_rej.json()["executed"] is False
            assert r_rej.json()["incident_status"] == "ESCALATED"
            assert (await client.get("/system/metrics")).json()["services"]["payment-api"] == "FAILED"

            # 3b. Scenario 3: Service Failure -> Approve -> RESOLVED
            r_svc_ok = await client.post("/incidents/simulate", json={"scenario": "service_failure", "auto_process": True})
            svc_ok_id = r_svc_ok.json()["id"]
            svc_apr_id = r_svc_ok.json()["workflow_state"]["remediation_plan"]["approval_id"]
            r_svc_app = await client.post(f"/approvals/{svc_apr_id}/approve", json={"decided_by": "capstone-reviewer"})
            assert r_svc_app.status_code == 200
            assert r_svc_app.json()["incident_status"] == "RESOLVED"
            assert (await client.get("/system/metrics")).json()["db_connected"] is True

            # 4. Normal condition -> NO_INCIDENT
            r_norm = await client.post("/incidents/simulate", json={"scenario": "normal", "auto_process": True})
            assert r_norm.status_code == 201
            assert r_norm.json()["status"] == "NO_INCIDENT"

            # 5. Failure + Rollback scenario
            r_fail = await client.post(
                "/incidents/simulate",
                json={"scenario": "high_cpu", "simulate_failure": True, "auto_process": True},
            )
            fail_id = r_fail.json()["id"]
            fail_apr_id = r_fail.json()["workflow_state"]["remediation_plan"]["approval_id"]
            r_fail_app = await client.post(f"/approvals/{fail_apr_id}/approve", json={"decided_by": "qa-tester"})
            assert r_fail_app.status_code == 200
            assert r_fail_app.json()["incident_status"] == "ESCALATED"
            rep_fail = (await client.get(f"/incidents/{fail_id}/report")).json()
            assert rep_fail["validation_outcome"]["is_recovered"] is False
            assert rep_fail["validation_outcome"]["rollback_triggered"] is True
            assert rep_fail["validation_outcome"]["rollback_status"] == "ROLLED_BACK"

            # Text report download format
            txt_resp = await client.get(f"/incidents/{svc_ok_id}/report", params={"format": "text"})
            assert txt_resp.status_code == 200
            assert "AUTONOMOUS IT INCIDENT RESOLUTION REPORT" in txt_resp.text

            # Timeline endpoint check
            tl_resp = await client.get(f"/incidents/{svc_ok_id}/timeline")
            assert tl_resp.status_code == 200
            assert len(tl_resp.json()["events"]) >= 7

            # Evaluation endpoints check
            ev_run = await client.post("/evaluation/run")
            assert ev_run.status_code == 200
            assert ev_run.json()["passed_cases"] == 7
            ev_latest = await client.get("/evaluation/latest")
            assert ev_latest.status_code == 200
            assert ev_latest.json()["has_results"] is True

            # Reset simulator at end
            await client.post("/system/reset")

    asyncio.run(_run_e2e())

    # Verify SQLite persistence across fresh app instance pointing to same DB
    reset_engine()
    app_restarted = create_app()

    async def _check_persistence():
        transport = httpx.ASGITransport(app=app_restarted)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            incidents = (await client.get("/incidents")).json()
            assert len(incidents) == 6

    asyncio.run(_check_persistence())
    reset_engine()
    get_settings.cache_clear()
