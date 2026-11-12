"""Streamlit IT Operations Dashboard for Autonomous IT Incident Resolution."""

from __future__ import annotations

import json
import os
from typing import Any, Dict, List, Optional

import pandas as pd
import plotly.graph_objects as go
import requests
import streamlit as st


DEFAULT_BACKEND_URL = os.getenv("BACKEND_URL", "http://localhost:8000").rstrip("/")


def api_get(base_url: str, path: str, params: Optional[Dict[str, Any]] = None) -> Any:
    """Perform a GET request against the FastAPI backend."""
    resp = requests.get(f"{base_url}{path}", params=params, timeout=30)
    resp.raise_for_status()
    if "application/json" in resp.headers.get("content-type", ""):
        return resp.json()
    return resp.text


def api_post(base_url: str, path: str, payload: Optional[Dict[str, Any]] = None) -> Any:
    """Perform a POST request against the FastAPI backend."""
    resp = requests.post(f"{base_url}{path}", json=payload, timeout=90)
    resp.raise_for_status()
    return resp.json()


def _severity_badge(severity: str) -> str:
    colors = {
        "CRITICAL": "#EF4444",
        "WARNING": "#F59E0B",
        "NORMAL": "#10B981",
        "HEALTHY": "#10B981",
        "RESOLVED": "#10B981",
        "AWAITING_APPROVAL": "#F59E0B",
        "ESCALATED": "#F97316",
        "FAILED": "#EF4444",
        "DEGRADED": "#F59E0B",
        "UNREACHABLE": "#EF4444",
        "NO_INCIDENT": "#38BDF8",
    }
    color = colors.get(severity.upper(), "#64748B")
    return (
        f"<span style='background:{color}22;color:{color};border:1px solid {color};"
        f"padding:2px 8px;border-radius:12px;font-size:0.78rem;font-weight:600;'>{severity}</span>"
    )


def _metric_gauge_chart(cpu: float, mem: float, disk: float) -> go.Figure:
    fig = go.Figure(
        data=[
            go.Bar(
                x=["CPU Usage", "Memory Usage", "Disk Usage"],
                y=[cpu, mem, disk],
                marker_color=[
                    "#EF4444" if cpu >= 90 else ("#F59E0B" if cpu >= 70 else "#10B981"),
                    "#EF4444" if mem >= 90 else ("#F59E0B" if mem >= 75 else "#38BDF8"),
                    "#EF4444" if disk >= 90 else ("#F59E0B" if disk >= 80 else "#10B981"),
                ],
                text=[f"{cpu:.1f}%", f"{mem:.1f}%", f"{disk:.1f}%"],
                textposition="auto",
            )
        ]
    )
    fig.update_layout(
        template="plotly_dark",
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(17,24,39,0.6)",
        yaxis=dict(range=[0, 105], title="Utilization (%)"),
        height=260,
        margin=dict(l=20, r=20, t=20, b=20),
    )
    return fig


def _before_after_chart(before: Dict[str, Any], after: Dict[str, Any]) -> go.Figure:
    categories = ["CPU (%)", "Memory (%)", "Disk (%)"]
    before_vals = [
        float(before.get("cpu_usage", 0.0)),
        float(before.get("memory_usage", 0.0)),
        float(before.get("disk_usage", 0.0)),
    ]
    after_vals = [
        float(after.get("cpu_usage", 0.0)),
        float(after.get("memory_usage", 0.0)),
        float(after.get("disk_usage", 0.0)),
    ]
    fig = go.Figure(
        data=[
            go.Bar(name="Before Remediation", x=categories, y=before_vals, marker_color="#EF4444"),
            go.Bar(name="After Remediation", x=categories, y=after_vals, marker_color="#10B981"),
        ]
    )
    fig.update_layout(
        barmode="group",
        template="plotly_dark",
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(17,24,39,0.6)",
        yaxis=dict(range=[0, 105], title="Utilization (%)"),
        height=270,
        margin=dict(l=20, r=20, t=25, b=20),
    )
    return fig


def render_dashboard() -> None:
    """Render the main Autonomous IT Incident Resolution Streamlit UI."""
    st.set_page_config(
        page_title="Autonomous IT Incident Resolution",
        page_icon="🛡️",
        layout="wide",
        initial_sidebar_state="expanded",
    )

    st.markdown(
        """
        <style>
        .block-container { padding-top: 1.5rem; padding-bottom: 2rem; }
        .kpi-card {
            background: #111827;
            border: 1px solid #1F2937;
            border-radius: 10px;
            padding: 14px 16px;
        }
        .kpi-label { color: #94A3B8; font-size: 0.82rem; margin-bottom: 4px; }
        .kpi-val { color: #F8FAFC; font-size: 1.55rem; font-weight: 700; }
        </style>
        """,
        unsafe_allow_html=True,
    )

    # Sidebar: Backend Connection + C. Incident Simulation
    st.sidebar.title("Control Panel")
    backend_url = st.sidebar.text_input("FastAPI Backend URL", value=DEFAULT_BACKEND_URL).rstrip("/")

    try:
        health = api_get(backend_url, "/health")
        st.sidebar.success(f"Backend: {health.get('status', 'healthy').upper()} | Model: {health.get('ollama_model')}")
    except Exception as exc:
        st.sidebar.error(f"Backend unreachable at {backend_url}: {exc}")
        st.title("Autonomous IT Incident Resolution")
        st.warning("Start the FastAPI backend first (`uvicorn backend.main:app --reload --port 8000`) and refresh.")
        return

    st.sidebar.divider()
    st.sidebar.subheader("Simulate Incident Scenario")
    scenario_labels = {
        "1. High CPU Utilization (application-server)": "high_cpu",
        "2. Disk Space Exhaustion (storage-service)": "disk_full",
        "3. Application Service Failure (payment-api)": "service_failure",
        "4. Normal Baseline Check (Negative Test)": "normal",
    }
    selected_label = st.sidebar.selectbox("Select Scenario", list(scenario_labels.keys()))
    simulate_failure = st.sidebar.checkbox(
        "Simulate Remediation Failure (Test Rollback)",
        value=False,
        help="Forces remediation execution to fail so Validation Agent demonstrates controlled rollback and escalation.",
    )

    if st.sidebar.button("Generate & Process Incident", type="primary", use_container_width=True):
        with st.spinner("Running LangGraph multi-agent workflow..."):
            created = api_post(
                backend_url,
                "/incidents/simulate",
                {
                    "scenario": scenario_labels[selected_label],
                    "simulate_failure": simulate_failure,
                    "auto_process": True,
                },
            )
            st.session_state["selected_incident_id"] = created["id"]
        st.sidebar.success(f"Created & processed {created['id']} ({created['status']})")
        st.rerun()

    if st.sidebar.button("Reset Simulated Infrastructure", use_container_width=True):
        api_post(backend_url, "/system/reset")
        st.sidebar.info("Simulated infrastructure reset to healthy baseline.")
        st.rerun()

    # Header
    st.title("Autonomous IT Incident Resolution")
    st.caption(
        "Phase 1 Prototype — Innovation Center, Center for AI & ML | "
        "All infrastructure metrics, logs, and remediation actions run in an isolated local simulator."
    )

    # Fetch core data
    incidents: List[Dict[str, Any]] = api_get(backend_url, "/incidents")
    pending_approvals: List[Dict[str, Any]] = api_get(backend_url, "/approvals/pending")
    sys_metrics: Dict[str, Any] = api_get(backend_url, "/system/metrics")

    # A. System Overview
    st.subheader("A. System Overview")
    total_inc = len(incidents)
    active_inc = sum(1 for i in incidents if i["status"] in {"DETECTED", "INVESTIGATING", "AWAITING_APPROVAL", "EXECUTED"})
    critical_inc = sum(1 for i in incidents if i["severity"] == "CRITICAL")
    resolved_inc = sum(1 for i in incidents if i["status"] == "RESOLVED")
    durations = [i["simulated_duration_seconds"] for i in incidents if i.get("simulated_duration_seconds") is not None]
    avg_res_time = f"{(sum(durations) / len(durations)):.2f}s" if durations else "N/A"

    k1, k2, k3, k4, k5, k6 = st.columns(6)
    for col, label, val in (
        (k1, "Total Incidents", str(total_inc)),
        (k2, "Active Incidents", str(active_inc)),
        (k3, "Critical Incidents", str(critical_inc)),
        (k4, "Resolved Incidents", str(resolved_inc)),
        (k5, "Pending Approvals", str(len(pending_approvals))),
        (k6, "Avg Simulated MTTR", avg_res_time),
    ):
        col.markdown(
            f"<div class='kpi-card'><div class='kpi-label'>{label}</div><div class='kpi-val'>{val}</div></div>",
            unsafe_allow_html=True,
        )

    ov_left, ov_right = st.columns([1.4, 1.0])
    with ov_left:
        st.plotly_chart(
            _metric_gauge_chart(
                sys_metrics["cpu_usage"],
                sys_metrics["memory_usage"],
                sys_metrics["disk_usage"],
            ),
            use_container_width=True,
        )
    with ov_right:
        st.markdown("**Simulated Infrastructure Health**")
        for svc_name, svc_status in sys_metrics.get("services", {}).items():
            st.markdown(f"- `{svc_name}`: {_severity_badge(svc_status)}", unsafe_allow_html=True)
        db_badge = _severity_badge("HEALTHY" if sys_metrics.get("db_connected") else "UNREACHABLE")
        st.markdown(f"- `db_connected`: {db_badge}", unsafe_allow_html=True)
        st.markdown(
            f"- Filesystem `{sys_metrics.get('filesystem')}`: **{sys_metrics.get('disk_available_gb')} GB free** "
            f"(sim temp cache: {sys_metrics.get('temp_files_gb')} GB)"
        )

    # G. Approval Center (surfaced prominently when pending approvals exist)
    st.divider()
    st.subheader("G. Human-in-the-Loop Approval Center")
    if not pending_approvals:
        st.info("No pending human approvals. Trigger a High CPU or Service Failure scenario to inspect the safety gate.")
    else:
        for req in pending_approvals:
            with st.container(border=True):
                c1, c2 = st.columns([2.2, 1.0])
                with c1:
                    st.markdown(
                        f"**Approval `{req['id']}`** for Incident `{req['incident_id']}` — "
                        f"Risk: {_severity_badge(req['risk_level'])}",
                        unsafe_allow_html=True,
                    )
                    st.write(f"**Proposed Action:** `{req['proposed_action']}`")
                    st.write(f"**Reason:** {req['reason']}")
                    st.write(f"**Expected Outcome:** {req['expected_outcome']}")
                with c2:
                    op_name = st.text_input("Operator ID", value="demo-operator", key=f"op_{req['id']}")
                    comment = st.text_input("Decision Note", value="", key=f"cmt_{req['id']}")
                    b1, b2 = st.columns(2)
                    if b1.button("Approve", key=f"app_{req['id']}", type="primary", use_container_width=True):
                        with st.spinner("Executing approved remediation and validating recovery..."):
                            res = api_post(
                                backend_url,
                                f"/approvals/{req['id']}/approve",
                                {"decided_by": op_name, "comment": comment or None},
                            )
                        st.session_state["selected_incident_id"] = req["incident_id"]
                        st.success(res["message"])
                        st.rerun()
                    if b2.button("Reject", key=f"rej_{req['id']}", use_container_width=True):
                        res = api_post(
                            backend_url,
                            f"/approvals/{req['id']}/reject",
                            {"decided_by": op_name, "comment": comment or None},
                        )
                        st.session_state["selected_incident_id"] = req["incident_id"]
                        st.warning(res["message"])
                        st.rerun()

    # B. Incident Management
    st.divider()
    st.subheader("B. Incident Management")
    if not incidents:
        st.info("No incidents recorded yet. Use **Generate & Process Incident** in the sidebar to begin.")
    else:
        df_inc = pd.DataFrame(incidents)[
            ["id", "incident_type", "severity", "affected_service", "status", "detected_at", "simulated_duration_seconds"]
        ]
        st.dataframe(df_inc, use_container_width=True, hide_index=True)

        incident_ids = [i["id"] for i in incidents]
        default_id = st.session_state.get("selected_incident_id")
        default_idx = incident_ids.index(default_id) if default_id in incident_ids else 0
        selected_id = st.selectbox("Inspect Incident Details", incident_ids, index=default_idx)
        st.session_state["selected_incident_id"] = selected_id

        report: Dict[str, Any] = api_get(backend_url, f"/incidents/{selected_id}/report")
        timeline: Dict[str, Any] = api_get(backend_url, f"/incidents/{selected_id}/timeline")

        tab_timeline, tab_rca, tab_rag, tab_report = st.tabs(
            [
                "D. Agent Execution Timeline",
                "E. Root Cause Analysis",
                "F. RAG Knowledge Retrieval",
                "H. Resolution Report & Audit",
            ]
        )

        # D. Agent Execution Timeline
        with tab_timeline:
            events = timeline.get("events", [])
            if not events:
                st.write("No agent execution events logged.")
            else:
                for ev in events:
                    ts = ev["timestamp"].split("T")[-1][:8]
                    st.markdown(
                        f"**`{ts}`** — **{ev['agent_name']}** ({_severity_badge(ev['status'])}) — {ev['message']}",
                        unsafe_allow_html=True,
                    )

        # E. Root Cause Analysis
        with tab_rca:
            rca = report.get("root_cause_analysis")
            if not rca:
                st.info("No Root Cause Analysis generated for this incident (e.g., baseline normal check).")
            else:
                r1, r2, r3 = st.columns([2, 1, 1])
                r1.markdown(f"**Probable Root Cause:** {rca['probable_cause']}")
                r2.metric("Confidence Score", f"{rca['confidence_score']:.0%}")
                r3.metric("Reasoning Source", rca["reasoning_source"])
                st.write(f"**Reasoning Summary:** {rca['reasoning_summary']}")

                c_ev, c_logs = st.columns(2)
                with c_ev:
                    st.markdown("**Supporting Evidence & Monitoring Observations**")
                    for item in rca.get("supporting_evidence", []):
                        st.markdown(f"- {item}")
                with c_logs:
                    st.markdown("**Correlated Raw Logs**")
                    st.code("\n".join(report.get("raw_logs", [])), language="text")

        # F. RAG Knowledge Retrieval
        with tab_rag:
            runbooks = report.get("retrieved_runbooks", [])
            if not runbooks:
                st.info("No runbook excerpts were retrieved for this incident.")
            else:
                st.markdown(f"**Top Retrieved Runbook:** `{runbooks[0]['runbook_name']}`")
                for rb in runbooks:
                    with st.expander(
                        f"{rb['runbook_name']} — {rb['section_title']} (Relevance: {rb['relevance_score']:.3f})",
                        expanded=True,
                    ):
                        st.markdown(rb["excerpt"])

        # H. Incident Resolution Report
        with tab_report:
            inc_sum = report["incident_summary"]
            st.markdown(
                f"**Incident `{inc_sum['incident_id']}`** | Status: {_severity_badge(inc_sum['status'])} | "
                f"Duration: **{inc_sum.get('simulated_duration_seconds') or 'Pending'}s**",
                unsafe_allow_html=True,
            )
            ba = report.get("before_and_after_metrics", {})
            before_m = ba.get("before") or {}
            after_m = ba.get("after") or {}
            if before_m and after_m:
                st.plotly_chart(_before_after_chart(before_m, after_m), use_container_width=True)
            elif before_m:
                st.json({"before_metrics": before_m})

            val = report.get("validation_outcome")
            if val:
                if val["is_recovered"]:
                    st.success(f"Validation PASSED: {val['validation_notes']}")
                else:
                    st.error(f"Validation FAILED (Rollback={val['rollback_status']}): {val['validation_notes']}")

            c_act, c_app = st.columns(2)
            with c_act:
                st.markdown("**Remediation Actions**")
                st.json(report.get("remediation_actions", []))
            with c_app:
                st.markdown("**Approval Details**")
                st.json(report.get("approval_details", []))

            st.markdown("**SQLite Audit Trail**")
            audit_df = pd.DataFrame(report.get("audit_events", []))
            if not audit_df.empty:
                st.dataframe(audit_df, use_container_width=True, hide_index=True)

            text_report = api_get(backend_url, f"/incidents/{selected_id}/report", params={"format": "text"})
            d1, d2 = st.columns(2)
            d1.download_button(
                "Download Report (JSON)",
                data=json.dumps(report, indent=2),
                file_name=f"{selected_id}_report.json",
                mime="application/json",
                use_container_width=True,
            )
            d2.download_button(
                "Download Report (TXT)",
                data=str(text_report),
                file_name=f"{selected_id}_report.txt",
                mime="text/plain",
                use_container_width=True,
            )

    # I. Evaluation Metrics (Section 11)
    st.divider()
    st.subheader("I. Evaluation Metrics (Simulated Test Dataset)")
    ev_col1, ev_col2 = st.columns([1, 3])
    if ev_col1.button("Run Simulated Evaluation Suite", use_container_width=True):
        with st.spinner("Executing 7 simulated evaluation scenarios (positive, negative, safety, rollback)..."):
            eval_data = api_post(backend_url, "/evaluation/run")
        st.success(f"Evaluation completed: {eval_data['passed_cases']}/{eval_data['total_cases']} cases passed.")
    else:
        eval_data = api_get(backend_url, "/evaluation/latest")

    if eval_data.get("metrics"):
        m = eval_data["metrics"]
        m_cols = st.columns(7)
        metric_items = [
            ("Detection Acc.", f"{m['incident_detection_accuracy']:.0%}"),
            ("RCA Accuracy", f"{m['root_cause_identification_accuracy']:.0%}"),
            ("RAG Relevance", f"{m['runbook_retrieval_relevance']:.0%}"),
            ("Remediation Rate", f"{m['successful_remediation_rate']:.0%}"),
            ("Mean Sim. MTTR", f"{m['mean_simulated_time_to_resolution_sec']}s"),
            ("Approval Compl.", f"{m['human_approval_compliance']:.0%}"),
            ("Unsafe Prevented", f"{m['unsafe_action_prevention']:.0%}"),
        ]
        for col, (lbl, val) in zip(m_cols, metric_items):
            col.metric(lbl, val)

        with st.expander("View Simulated Evaluation Case Results", expanded=False):
            st.caption(f"Dataset: {eval_data.get('dataset_label')} | Evaluated at: {eval_data.get('evaluated_at')}")
            st.dataframe(pd.DataFrame(eval_data.get("case_results", [])), use_container_width=True, hide_index=True)
    else:
        ev_col2.info("Click **Run Simulated Evaluation Suite** to compute real metrics from the simulated dataset.")


if __name__ == "__main__":
    render_dashboard()
