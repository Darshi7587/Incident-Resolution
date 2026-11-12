"""LangGraph StateGraph workflow and shared IncidentState for multi-agent orchestration."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, TypedDict

from langgraph.graph import END, StateGraph
from sqlalchemy.orm import Session

from backend.agents.log_agent import LogAnalysisAgent
from backend.agents.monitoring_agent import MonitoringAgent
from backend.agents.rag_agent import RAGKnowledgeAgent
from backend.agents.root_cause_agent import RootCauseAnalysisAgent
from backend.config import Settings, get_settings
from backend.services.incident_simulator import SimulatedInfrastructure


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
    workflow_status: str  # INVESTIGATING, INVESTIGATED, AWAITING_APPROVAL, EXECUTED, RESOLVED, FAILED, ESCALATED, NO_INCIDENT
    should_continue: bool
    escalation_reason: Optional[str]
    error_message: Optional[str]
    events: List[Dict[str, str]]


def build_investigation_graph(
    db: Optional[Session] = None,
    settings: Optional[Settings] = None,
    infra: Optional[SimulatedInfrastructure] = None,
    rag_min_relevance: float = 0.25,
):
    """Build and compile the LangGraph StateGraph for multi-agent incident investigation."""
    cfg = settings or get_settings()
    infrastructure = infra or SimulatedInfrastructure()

    monitoring_agent = MonitoringAgent(settings=cfg, infra=infrastructure)
    log_agent = LogAnalysisAgent()
    rca_agent = RootCauseAnalysisAgent(settings=cfg)
    rag_agent = RAGKnowledgeAgent(settings=cfg)

    def _append_event(state: IncidentState, agent: str, status: str, detail: str) -> List[Dict[str, str]]:
        events = list(state.get("events", []))
        events.append({"agent": agent, "status": status, "detail": detail})
        return events

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
                "events": _append_event(
                    state,
                    log_agent.name,
                    "COMPLETED",
                    res["summary"],
                ),
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
                "events": _append_event(
                    state,
                    rag_agent.name,
                    "COMPLETED",
                    res["summary"],
                ),
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
        return "complete_investigation"

    def node_escalate_missing_runbook(state: IncidentState) -> Dict[str, Any]:
        reason = "No matching runbook evidence found in ChromaDB; escalated to human SRE."
        return {
            "workflow_status": "ESCALATED",
            "should_continue": False,
            "escalation_reason": reason,
            "events": _append_event(state, "Orchestrator Agent", "ESCALATED", reason),
        }

    def node_complete_investigation(state: IncidentState) -> Dict[str, Any]:
        return {
            "workflow_status": "INVESTIGATED",
            "events": _append_event(
                state,
                "Orchestrator Agent",
                "COMPLETED",
                "Investigation stage completed (Monitoring, Logs, RCA, RAG).",
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
    graph.add_node("complete_investigation", node_complete_investigation)

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
            "complete_investigation": "complete_investigation",
        },
    )
    graph.add_edge("escalate_missing_runbook", END)
    graph.add_edge("complete_investigation", END)

    return graph.compile()
