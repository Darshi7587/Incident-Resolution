"""Phase 5 tests: Markdown runbook ingestion, ChromaDB embeddings, and RAG semantic retrieval."""

from backend.agents.rag_agent import RAGKnowledgeAgent
from backend.config import get_settings
from backend.database.db import get_session_factory, init_db, reset_engine
from backend.database.models import RetrievedRunbook
from backend.rag.ingest import ingest_runbooks
from backend.rag.retriever import RunbookRetriever
from backend.schemas.incident import ScenarioType
from backend.services.incident_simulator import IncidentSimulator, SimulatedInfrastructure


def test_rag_ingest_and_retrieve_all_three_runbooks(tmp_path, monkeypatch):
    """Verify ChromaDB ingestion and accurate semantic retrieval for all 3 incident types."""
    db_file = tmp_path / "phase5_rag.db"
    chroma_dir = tmp_path / "chroma_test"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_file.as_posix()}")
    monkeypatch.setenv("CHROMA_PERSIST_DIR", str(chroma_dir))
    get_settings.cache_clear()
    reset_engine()
    init_db()

    settings = get_settings()
    stats = ingest_runbooks(settings=settings, force_reingest=True)
    assert stats["ingested_files"] == 3
    assert stats["total_chunks"] >= 15
    assert set(stats["runbooks"]) == {"cpu_high.md", "disk_full.md", "service_failure.md"}

    retriever = RunbookRetriever(settings=settings)
    rag_agent = RAGKnowledgeAgent(settings=settings, retriever=retriever)
    infra = SimulatedInfrastructure(state_file=tmp_path / "sim_state.json")
    sim = IncidentSimulator(infra=infra)

    SessionLocal = get_session_factory()
    with SessionLocal() as db:
        # 1. High CPU -> cpu_high.md
        inc1 = sim.generate_incident(db=db, scenario=ScenarioType.HIGH_CPU)
        res1 = rag_agent.retrieve(
            incident_type="high_cpu",
            affected_service="application-server",
            monitoring_result={"threshold_violations": [{"message": "CPU at 95%"}]},
            log_result={"error_signatures": ["CPU_THRESHOLD_EXCEEDED"]},
            rca_result={"probable_cause": "Runaway worker thread pool exhausting CPU on application-server"},
            incident_id=inc1.id,
            db=db,
        )
        assert res1["evidence_found"] is True
        assert res1["primary_runbook"] == "cpu_high.md"
        assert len(res1["retrieved_sections"]) > 0

        # 2. Disk Full -> disk_full.md
        inc2 = sim.generate_incident(db=db, scenario=ScenarioType.DISK_FULL)
        res2 = rag_agent.retrieve(
            incident_type="disk_full",
            affected_service="storage-service",
            monitoring_result={"threshold_violations": [{"message": "Disk at 96% on /dev/sda1"}]},
            log_result={"error_signatures": ["DISK_SPACE_CRITICAL"]},
            rca_result={"probable_cause": "Temporary file accumulation filling filesystem /dev/sda1"},
            incident_id=inc2.id,
            db=db,
        )
        assert res2["evidence_found"] is True
        assert res2["primary_runbook"] == "disk_full.md"

        # 3. Service Failure -> service_failure.md
        inc3 = sim.generate_incident(db=db, scenario=ScenarioType.SERVICE_FAILURE)
        res3 = rag_agent.retrieve(
            incident_type="service_failure",
            affected_service="payment-api",
            monitoring_result={"threshold_violations": [{"message": "payment-api FAILED, db_connected=False"}]},
            log_result={"error_signatures": ["SERVICE_FAILURE", "DB_CONNECTION_REFUSED"]},
            rca_result={"probable_cause": "Database connection refused causing payment-api outage"},
            incident_id=inc3.id,
            db=db,
        )
        assert res3["evidence_found"] is True
        assert res3["primary_runbook"] == "service_failure.md"

        # Missing evidence test (high min_relevance threshold with unrelated query)
        res_missing = rag_agent.retrieve(
            incident_type="unknown_quantum_flux",
            affected_service="alien-service",
            monitoring_result={"threshold_violations": []},
            log_result={"error_signatures": []},
            rca_result={"probable_cause": "Unrelated astronomy telescope calibration drift"},
            min_relevance=0.85,
        )
        assert res_missing["evidence_found"] is False
        assert res_missing["primary_runbook"] is None

        assert db.query(RetrievedRunbook).count() >= 3

    reset_engine()
    get_settings.cache_clear()
