"""Runbook ingestion pipeline: Markdown section chunking, embeddings, and ChromaDB storage."""

from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional

import chromadb
from sentence_transformers import SentenceTransformer

from backend.config import Settings, get_settings

COLLECTION_NAME = "it_runbooks"
SECTION_HEADER_RE = re.compile(r"^##\s+(.+)$", re.MULTILINE)


@lru_cache(maxsize=2)
def get_embedding_model(model_name: str) -> SentenceTransformer:
    """Load and cache SentenceTransformer model."""
    return SentenceTransformer(model_name)


def chunk_markdown_runbook(file_path: Path) -> List[Dict[str, Any]]:
    """Split a Markdown runbook into section-level chunks with rich metadata."""
    text = file_path.read_text(encoding="utf-8")
    lines = text.splitlines()
    runbook_name = file_path.name

    chunks: List[Dict[str, Any]] = []
    current_section = "Overview"
    buffer: List[str] = []

    def _flush(section_title: str, content_lines: List[str], idx: int) -> None:
        body = "\n".join(content_lines).strip()
        if not body:
            return
        chunks.append(
            {
                "id": f"{runbook_name}::chunk_{idx}",
                "runbook_name": runbook_name,
                "section_title": section_title,
                "source_path": str(file_path),
                "content": f"Runbook: {runbook_name}\nSection: {section_title}\n\n{body}",
            }
        )

    chunk_idx = 0
    for line in lines:
        if line.startswith("## "):
            _flush(current_section, buffer, chunk_idx)
            if buffer and "\n".join(buffer).strip():
                chunk_idx += 1
            current_section = line[3:].strip()
            buffer = []
        elif line.startswith("# ") and current_section == "Overview" and not buffer:
            # Include document title in Overview context
            buffer.append(line)
        else:
            buffer.append(line)

    _flush(current_section, buffer, chunk_idx)
    return chunks


def get_chroma_client(persist_dir: str) -> chromadb.PersistentClient:
    """Return a persistent ChromaDB client for the given directory."""
    Path(persist_dir).mkdir(parents=True, exist_ok=True)
    return chromadb.PersistentClient(path=persist_dir)


def ingest_runbooks(
    settings: Optional[Settings] = None,
    force_reingest: bool = False,
) -> Dict[str, Any]:
    """Ingest all Markdown runbooks from runbooks_dir into ChromaDB with embeddings."""
    cfg = settings or get_settings()
    runbooks_path = Path(cfg.runbooks_dir)
    md_files = sorted(p for p in runbooks_path.glob("*.md") if p.is_file())

    client = get_chroma_client(cfg.chroma_persist_dir)
    if force_reingest:
        try:
            client.delete_collection(name=COLLECTION_NAME)
        except Exception:
            pass

    collection = client.get_or_create_collection(
        name=COLLECTION_NAME,
        metadata={"hnsw:space": "cosine"},
    )

    if not md_files:
        return {"ingested_files": 0, "total_chunks": collection.count(), "runbooks": []}

    all_chunks: List[Dict[str, Any]] = []
    for md_file in md_files:
        all_chunks.extend(chunk_markdown_runbook(md_file))

    if not all_chunks:
        return {"ingested_files": len(md_files), "total_chunks": 0, "runbooks": [f.name for f in md_files]}

    model = get_embedding_model(cfg.embedding_model)
    documents = [c["content"] for c in all_chunks]
    embeddings = model.encode(documents, normalize_embeddings=True).tolist()
    ids = [c["id"] for c in all_chunks]
    metadatas = [
        {
            "runbook_name": c["runbook_name"],
            "section_title": c["section_title"],
            "source_path": c["source_path"],
        }
        for c in all_chunks
    ]

    collection.upsert(
        ids=ids,
        documents=documents,
        embeddings=embeddings,
        metadatas=metadatas,
    )

    return {
        "ingested_files": len(md_files),
        "total_chunks": len(all_chunks),
        "runbooks": [f.name for f in md_files],
    }
