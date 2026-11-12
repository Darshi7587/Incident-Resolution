"""FastAPI endpoint for inspecting local Markdown runbooks and semantic search."""

from pathlib import Path
from typing import Any, Dict, List

from fastapi import APIRouter, Query

from backend.config import get_settings
from backend.rag.ingest import ingest_runbooks
from backend.rag.retriever import RunbookRetriever

router = APIRouter(tags=["RAG Runbooks"])


@router.get("/runbooks")
def list_runbooks() -> Dict[str, Any]:
    """List available Markdown runbooks and their full contents."""
    settings = get_settings()
    runbooks_dir = Path(settings.runbooks_dir)
    files = sorted(p for p in runbooks_dir.glob("*.md") if p.is_file())
    items: List[Dict[str, str]] = []
    for f in files:
        content = f.read_text(encoding="utf-8")
        first_line = content.splitlines()[0].lstrip("# ").strip() if content else f.name
        items.append({"filename": f.name, "title": first_line, "content": content})
    return {"count": len(items), "runbooks": items}


@router.post("/runbooks/ingest")
def trigger_ingest(force: bool = Query(default=False)) -> Dict[str, Any]:
    """Ingest or re-ingest local Markdown runbooks into ChromaDB."""
    return ingest_runbooks(force_reingest=force)


@router.get("/runbooks/search")
def search_runbooks(q: str = Query(..., min_length=2), top_k: int = Query(default=3, ge=1, le=10)) -> Dict[str, Any]:
    """Semantic search across ingested runbooks in ChromaDB."""
    retriever = RunbookRetriever()
    matches = retriever.search(query=q, top_k=top_k)
    return {"query": q, "count": len(matches), "results": matches}
