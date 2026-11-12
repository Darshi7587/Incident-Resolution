"""LangGraph StateGraph workflows and shared IncidentState for multi-agent orchestration."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, TypedDict

from langgraph.graph import END, StateGraph
from sqlalchemy.orm import Session

from backend.agents.log_agent import LogAnalysisAgent
from backend.agents.monitoring_agent import MonitoringAgent
from backend.agents.rag_agent import RAGKnowledgeAgent
from backend.agents.remediation_agent import RemediationPlanningAgent
from backend.agents.root_cause_agent import RootCauseAnalysisAgent
from backend.agents.validation_agent import ValidationAgent
from backend.config import Settings, get_settings
from backend.services.incident_simulator import SimulatedInfrastructure
from backend.services.remediation_executor import RemediationExecutor


class IncidentState(TypedDict, total=False):
    """Shared state passed across all LangGraph agent nodes."""

    incident_id: str
    incident_type: str
    affected_service: str
    simulate_failure: bool
    metrics_snapshot: Dict[str, Any]
    raw_logs: List[str]

    # Agent outputs
    monitoring_result: Dict[str, Any]
    log_result: Dict[str, Any]
    rca_result: Dict[str, Any]
    rag_result: Dict[str, Any]
    remediation_plan: Dict[str, Any]
    approval_result: Dict[str, Any]
    execution_result: Dict[str, Any]
    validation_result: Dict[str, Any]

    # Control / Routing
    workflow_status: str  # INVESTIGATING, AWAITING_APPROVAL, EXECUTED, REMEDIATION_FAILED, RESOLVED, FAILED, ESCALATED, NO_INCIDENT
    should_continue: bool
    escalation_reason: Optional[str]
    error_message: Optional[str]
    events: List[Dict[str, str]]


def _append_event(state: IncidentState, agent: str, status: str, detail: str) -> List[Dict[str, str]]:
    events = list(state.get("events", []))
    events.append({"agent": agent, "status": status, "detail": detail})
    return events


def build_incident_graph(
    db: Optional[Session] = None,
    settings: Optional[Settings] = None,
    infra: Optional[SimulatedInfrastructure] = None,
    rag_min_relevance: float = 0.25,
):
    """Build and compile the LangGraph StateGraph from triage through remediation/approval gate."""
    cfg = settings or get_settings()
    infrastructure = infra or SimulatedInfrastructure()

    monitoring_agent = MonitoringAgent(settings=cfg, infra=infrastructure)
    log_agent = LogAnalysisAgent()
    rca_agent = RootCauseAnalysisAgent(settings=cfg)
    rag_agent = RAGKnowledgeAgent(settings=cfg)
    remediation_agent = RemediationPlanningAgent(settings=cfg)
    executor = RemediationExecutor(infra=infrastructure)
    validation_agent = ValidationAgent(settings=cfg, infra=infrastructure)

    def node_monitoring(state: IncidentState) -> Dict[str, Any]:
        try:
            res = monitoring_agent.analyze(
                metrics=state.get("metrics_snapshot"),
                incident_id=state["incident_id"],
                db=db,
            )
            return {
                "monitoring_result": res,
                "events": _append_event(
                    state,
                    monitoring_agent.name,
                    "COMPLETED",
                    f"Severity={res['severity']}, violations={len(res['threshold_violations'])}",
                ),
            }
        except Exception as exc:
            return {
                "workflow_status": "FAILED",
                "should_continue": False,
                "error_message": f"Monitoring Agent failed: {exc}",
                "events": _append_event(state, monitoring_agent.name, "FAILED", str(exc)),
            }

    def node_log_analysis(state: IncidentState) -> Dict[str, Any]:
        if not state.get("should_continue", True):
            return {}
        try:
            res = log_agent.analyze(
                logs=state.get("raw_logs", []),
                affected_service=state.get("affected_service"),
                incident_id=state["incident_id"],
                db=db,
            )
            return {
                "log_result": res,
                "events": _append_event(state, log_agent.name, "COMPLETED", res["summary"]),
            }
        except Exception as exc:
            return {
                "workflow_status": "FAILED",
                "should_continue": False,
                "error_message": f"Log Analysis Agent failed: {exc}",
                "events": _append_event(state, log_agent.name, "FAILED", str(exc)),
            }

    def route_after_triage(state: IncidentState) -> str:
        if not state.get("should_continue", True):
            return "stop_failed"
        mon = state.get("monitoring_result", {})
        log_res = state.get("log_result", {})
        counts = log_res.get("counts_by_level", {})
        has_bad_logs = (counts.get("CRITICAL", 0) + counts.get("ERROR", 0)) > 0
        if mon.get("severity") == "NORMAL" and not has_bad_logs:
            return "no_incident"
        return "run_rca"

    def node_no_incident(state: IncidentState) -> Dict[str, Any]:
        return {
            "workflow_status": "NO_INCIDENT",
            "should_continue": False,
            "events": _append_event(
                state,
                "Orchestrator Agent",
                "COMPLETED",
                "No abnormal thresholds or critical errors detected; stopping workflow.",
            ),
        }

    def node_stop_failed(state: IncidentState) -> Dict[str, Any]:
        return {
            "workflow_status": "FAILED",
            "should_continue": False,
            "events": _append_event(
                state,
                "Orchestrator Agent",
                "FAILED",
                state.get("error_message", "Workflow stopped due to agent execution failure."),
            ),
        }

    def node_root_cause(state: IncidentState) -> Dict[str, Any]:
        try:
            res = rca_agent.analyze(
                monitoring_result=state.get("monitoring_result", {}),
                log_result=state.get("log_result", {}),
                incident_type=state.get("incident_type", "unknown"),
                incident_id=state["incident_id"],
                db=db,
            )
            return {
                "rca_result": res,
                "events": _append_event(
                    state,
                    rca_agent.name,
                    "COMPLETED",
                    f"{res['probable_cause']} (confidence={res['confidence_score']})",
                ),
            }
        except Exception as exc:
            return {
                "workflow_status": "FAILED",
                "should_continue": False,
                "error_message": f"Root Cause Analysis Agent failed: {exc}",
                "events": _append_event(state, rca_agent.name, "FAILED", str(exc)),
            }

    def node_rag_retrieval(state: IncidentState) -> Dict[str, Any]:
        if not state.get("should_continue", True):
            return {}
        try:
            res = rag_agent.retrieve(
                incident_type=state.get("incident_type", "unknown"),
                affected_service=state.get("affected_service", "unknown"),
                monitoring_result=state.get("monitoring_result", {}),
                log_result=state.get("log_result", {}),
                rca_result=state.get("rca_result", {}),
                incident_id=state["incident_id"],
                db=db,
                min_relevance=rag_min_relevance,
            )
            return {
                "rag_result": res,
                "events": _append_event(state, rag_agent.name, "COMPLETED", res["summary"]),
            }
        except Exception as exc:
            return {
                "workflow_status": "FAILED",
                "should_continue": False,
                "error_message": f"RAG Knowledge Agent failed: {exc}",
                "events": _append_event(state, rag_agent.name, "FAILED", str(exc)),
            }

    def route_after_rag(state: IncidentState) -> str:
        if not state.get("should_continue", True):
            return "stop_failed"
        rag = state.get("rag_result", {})
        if not rag.get("evidence_found", False):
            return "escalate_missing_runbook"
        return "plan_remediation"

    def node_escalate_missing_runbook(state: IncidentState) -> Dict[str, Any]:
        reason = "No matching runbook evidence found in ChromaDB; escalated to human SRE."
        return {
            "workflow_status": "ESCALATED",
            "should_continue": False,
            "escalation_reason": reason,
            "events": _append_event(state, "Orchestrator Agent", "ESCALATED", reason),
        }

    def node_remediation_planning(state: IncidentState) -> Dict[str, Any]:
        try:
            plan = remediation_agent.plan(
                incident_id=state["incident_id"],
                incident_type=state.get("incident_type", "unknown"),
                affected_service=state.get("affected_service", "unknown"),
                rca_result=state.get("rca_result", {}),
                rag_result=state.get("rag_result", {}),
                before_metrics=state.get("metrics_snapshot"),
                db=db,
            )
            return {
                "remediation_plan": plan,
                "events": _append_event(
                    state,
                    remediation_agent.name,
                    "COMPLETED",
                    f"Proposed {plan['action_name']} (risk={plan['risk_level']}, approval_required={plan['requires_approval']})",
                ),
            }
        except Exception as exc:
            return {
                "workflow_status": "FAILED",
                "should_continue": False,
                "error_message": f"Remediation Planning Agent failed: {exc}",
                "events": _append_event(state, remediation_agent.name, "FAILED", str(exc)),
            }

    def route_after_planning(state: IncidentState) -> str:
        if not state.get("should_continue", True):
            return "stop_failed"
        plan = state.get("remediation_plan", {})
        if plan.get("requires_approval", True):
            return "pause_for_approval"
        return "execute_remediation"

    def node_pause_for_approval(state: IncidentState) -> Dict[str, Any]:
        plan = state.get("remediation_plan", {})
        return {
            "workflow_status": "AWAITING_APPROVAL",
            "should_continue": False,
            "events": _append_event(
                state,
                "Risk Engine",
                "AWAITING_APPROVAL",
                f"Paused workflow for human approval ({plan.get('approval_id')}) on {plan.get('action_name')}.",
            ),
        }

    def node_execute_remediation(state: IncidentState) -> Dict[str, Any]:
        plan = state.get("remediation_plan", {})
        approval_res = state.get("approval_result", {})
        approval_status = approval_res.get("status") or plan.get("approval_status", "PENDING")

        exec_res = executor.execute_action(
            action_name=plan["action_name"],
            target_service=plan["target_service"],
            approval_status=approval_status,
            simulate_failure=bool(state.get("simulate_failure", False)),
            action_id=plan.get("action_id"),
            incident_id=state["incident_id"],
            db=db,
        )
        next_status = "EXECUTED" if exec_res["action_succeeded"] else "REMEDIATION_FAILED"
        return {
            "execution_result": exec_res,
            "workflow_status": next_status,
            "events": _append_event(
                state,
                "Remediation Executor",
                exec_res["execution_status"],
                exec_res["message"],
            ),
        }

    def node_validate_recovery(state: IncidentState) -> Dict[str, Any]:
        plan = state.get("remediation_plan", {})
        val_res = validation_agent.validate(
            incident_id=state["incident_id"],
            target_service=plan.get("target_service", state.get("affected_service", "unknown")),
            before_metrics=state.get("metrics_snapshot", {}),
            execution_result=state.get("execution_result", {}),
            db=db,
        )
        return {
            "validation_result": val_res,
            "workflow_status": val_res["final_status"],
            "events": _append_event(
                state,
                validation_agent.name,
                val_res["final_status"],
                val_res["validation_notes"],
            ),
        }

    graph = StateGraph(IncidentState)
    graph.add_node("monitoring", node_monitoring)
    graph.add_node("log_analysis", node_log_analysis)
    graph.add_node("no_incident", node_no_incident)
    graph.add_node("stop_failed", node_stop_failed)
    graph.add_node("root_cause", node_root_cause)
    graph.add_node("rag_retrieval", node_rag_retrieval)
    graph.add_node("escalate_missing_runbook", node_escalate_missing_runbook)
    graph.add_node("remediation_planning", node_remediation_planning)
    graph.add_node("pause_for_approval", node_pause_for_approval)
    graph.add_node("execute_remediation", node_execute_remediation)
    graph.add_node("validate_recovery", node_validate_recovery)

    graph.set_entry_point("monitoring")
    graph.add_edge("monitoring", "log_analysis")
    graph.add_conditional_edges(
        "log_analysis",
        route_after_triage,
        {
            "no_incident": "no_incident",
            "stop_failed": "stop_failed",
            "run_rca": "root_cause",
        },
    )
    graph.add_edge("no_incident", END)
    graph.add_edge("stop_failed", END)
    graph.add_edge("root_cause", "rag_retrieval")
    graph.add_conditional_edges(
        "rag_retrieval",
        route_after_rag,
        {
            "stop_failed": "stop_failed",
            "escalate_missing_runbook": "escalate_missing_runbook",
            "plan_remediation": "remediation_planning",
        },
    )
    graph.add_edge("escalate_missing_runbook", END)
    graph.add_conditional_edges(
        "remediation_planning",
        route_after_planning,
        {
            "stop_failed": "stop_failed",
            "pause_for_approval": "pause_for_approval",
            "execute_remediation": "execute_remediation",
        },
    )
    graph.add_edge("pause_for_approval", END)
    graph.add_edge("execute_remediation", "validate_recovery")
    graph.add_edge("validate_recovery", END)

    return graph.compile()


def build_resume_graph(
    db: Optional[Session] = None,
    settings: Optional[Settings] = None,
    infra: Optional[SimulatedInfrastructure] = None,
):
    """Build LangGraph StateGraph to resume paused workflow after human approval."""
    cfg = settings or get_settings()
    infrastructure = infra or SimulatedInfrastructure()
    executor = RemediationExecutor(infra=infrastructure)
    validation_agent = ValidationAgent(settings=cfg, infra=infrastructure)

    def node_execute_approved(state: IncidentState) -> Dict[str, Any]:
        plan = state.get("remediation_plan", {})
        approval_res = state.get("approval_result", {})
        if approval_res.get("status") != "APPROVED":
            reason = "Workflow resumed without APPROVED status; refusing remediation execution."
            return {
                "workflow_status": "ESCALATED",
                "should_continue": False,
                "escalation_reason": reason,
                "events": _append_event(state, "Orchestrator Agent", "BLOCKED", reason),
            }

        exec_res = executor.execute_action(
            action_name=plan["action_name"],
            target_service=plan["target_service"],
            approval_status="APPROVED",
            simulate_failure=bool(state.get("simulate_failure", False)),
            action_id=plan.get("action_id"),
            incident_id=state["incident_id"],
            db=db,
        )
        next_status = "EXECUTED" if exec_res["action_succeeded"] else "REMEDIATION_FAILED"
        return {
            "execution_result": exec_res,
            "workflow_status": next_status,
            "should_continue": True,
            "events": _append_event(
                state,
                "Remediation Executor",
                exec_res["execution_status"],
                exec_res["message"],
            ),
        }

    def route_after_resume_exec(state: IncidentState) -> str:
        if not state.get("should_continue", True):
            return "end_blocked"
        return "validate_recovery"

    def node_validate_recovery(state: IncidentState) -> Dict[str, Any]:
        plan = state.get("remediation_plan", {})
        val_res = validation_agent.validate(
            incident_id=state["incident_id"],
            target_service=plan.get("target_service", state.get("affected_service", "unknown")),
            before_metrics=state.get("metrics_snapshot", {}),
            execution_result=state.get("execution_result", {}),
            db=db,
        )
        return {
            "validation_result": val_res,
            "workflow_status": val_res["final_status"],
            "events": _append_event(
                state,
                validation_agent.name,
                val_res["final_status"],
                val_res["validation_notes"],
            ),
        }

    graph = StateGraph(IncidentState)
    graph.add_node("execute_approved", node_execute_approved)
    graph.add_node("validate_recovery", node_validate_recovery)
    graph.set_entry_point("execute_approved")
    graph.add_conditional_edges(
        "execute_approved",
        route_after_resume_exec,
        {
            "end_blocked": END,
            "validate_recovery": "validate_recovery",
        },
    )
    graph.add_edge("validate_recovery", END)
    return graph.compile()


# Backwards-compatible alias for Phase 6 imports
build_investigation_graph = build_incident_graph
