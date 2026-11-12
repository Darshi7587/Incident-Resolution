"""Agent 5: RAG Knowledge Agent — retrieves relevant runbook procedures from ChromaDB."""

from __future__ import annotations

import json
from collections import Counter
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from backend.config import Settings, get_settings
from backend.database.models import AgentExecution, AuditLog, RetrievedRunbook
from backend.rag.retriever import RunbookRetriever


class RAGKnowledgeAgent:
    """Retrieves relevant runbook sections via semantic similarity search in ChromaDB."""

    name = "RAG Knowledge Agent"

    def __init__(
        self,
        settings: Optional[Settings] = None,
        retriever: Optional[RunbookRetriever] = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.retriever = retriever or RunbookRetriever(settings=self.settings)

    def build_query(
        self,
        incident_type: str,
        affected_service: str,
        monitoring_result: Dict[str, Any],
        log_result: Dict[str, Any],
        rca_result: Dict[str, Any],
    ) -> str:
        """Build a descriptive semantic query from incident telemetry and RCA hypothesis."""
        signatures = " ".join(log_result.get("error_signatures", []))
        violations = " ".join(v.get("message", "") for v in monitoring_result.get("threshold_violations", []))
        cause = rca_result.get("probable_cause", "")
        return (
            f"Incident type {incident_type} affecting service {affected_service}. "
            f"Probable root cause: {cause}. "
            f"Monitoring violations: {violations}. "
            f"Log signatures: {signatures}. Recommended remediation and validation procedures."
        ).strip()

    def retrieve(
        self,
        incident_type: str,
        affected_service: str,
        monitoring_result: Dict[str, Any],
        log_result: Dict[str, Any],
        rca_result: Dict[str, Any],
        incident_id: Optional[str] = None,
        db: Optional[Session] = None,
        top_k: int = 4,
        min_relevance: float = 0.25,
    ) -> Dict[str, Any]:
        """Retrieve relevant runbook excerpts and persist evidence in SQLite."""
        query = self.build_query(incident_type, affected_service, monitoring_result, log_result, rca_result)
        matches = self.retriever.search(query=query, top_k=top_k, min_relevance=min_relevance)

        if not matches:
            result = {
                "agent": self.name,
                "status": "COMPLETED",
                "evidence_found": False,
                "primary_runbook": None,
                "query_text": query,
                "retrieved_sections": [],
                "summary": "No relevant runbook evidence met the similarity threshold; escalate or use safe fallback.",
            }
        else:
            # Determine primary runbook by weighted score across retrieved sections
            score_by_book: Counter[str] = Counter()
            for m in matches:
                score_by_book[m["runbook_name"]] += m["relevance_score"]
            primary_runbook = score_by_book.most_common(1)[0][0]

            # Filter or prioritize sections from the primary runbook first while preserving top matches
            ordered = sorted(
                matches,
                key=lambda m: (m["runbook_name"] == primary_runbook, m["relevance_score"]),
                reverse=True,
            )

            result = {
                "agent": self.name,
                "status": "COMPLETED",
                "evidence_found": True,
                "primary_runbook": primary_runbook,
                "query_text": query,
                "retrieved_sections": ordered,
                "summary": (
                    f"Retrieved {len(ordered)} relevant section(s); primary runbook: {primary_runbook} "
                    f"(top relevance={ordered[0]['relevance_score']})."
                ),
            }

        if db is not None and incident_id is not None:
            for item in result["retrieved_sections"]:
                db.add(
                    RetrievedRunbook(
                        incident_id=incident_id,
                        runbook_name=item["runbook_name"],
                        section_title=item["section_title"],
                        excerpt=item["excerpt"],
                        relevance_score=item["relevance_score"],
                        query_text=query,
                    )
                )
            db.add(
                AgentExecution(
                    incident_id=incident_id,
                    agent_name=self.name,
                    status="COMPLETED",
                    message=result["summary"],
                    input_summary=json.dumps({"query": query[:300]}),
                    output_summary=json.dumps(
                        {
                            "evidence_found": result["evidence_found"],
                            "primary_runbook": result["primary_runbook"],
                            "section_count": len(result["retrieved_sections"]),
                        }
                    ),
                )
            )
            db.add(
                AuditLog(
                    incident_id=incident_id,
                    actor=self.name,
                    event_type="RUNBOOK_RETRIEVED",
                    what_happened=result["summary"],
                    evidence_json=json.dumps(
                        [
                            {
                                "runbook_name": s["runbook_name"],
                                "section_title": s["section_title"],
                                "relevance_score": s["relevance_score"],
                            }
                            for s in result["retrieved_sections"]
                        ]
                    ),
                )
            )
            db.commit()

        return result
