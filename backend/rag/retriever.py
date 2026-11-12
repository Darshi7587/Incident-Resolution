"""Semantic runbook retriever backed by ChromaDB and sentence-transformers."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from backend.config import Settings, get_settings
from backend.rag.ingest import COLLECTION_NAME, get_chroma_client, get_embedding_model, ingest_runbooks


class RunbookRetriever:
    """Queries ChromaDB runbook embeddings to retrieve relevant troubleshooting sections."""

    def __init__(self, settings: Optional[Settings] = None) -> None:
        self.settings = settings or get_settings()

    def ensure_ingested(self) -> None:
        """Ensure runbooks are ingested into ChromaDB if collection is empty."""
        client = get_chroma_client(self.settings.chroma_persist_dir)
        collection = client.get_or_create_collection(
            name=COLLECTION_NAME,
            metadata={"hnsw:space": "cosine"},
        )
        if collection.count() == 0:
            ingest_runbooks(settings=self.settings)

    def search(
        self,
        query: str,
        top_k: int = 4,
        min_relevance: float = 0.25,
    ) -> List[Dict[str, Any]]:
        """Perform semantic similarity search against ingested runbook chunks."""
        self.ensure_ingested()
        client = get_chroma_client(self.settings.chroma_persist_dir)
        collection = client.get_or_create_collection(
            name=COLLECTION_NAME,
            metadata={"hnsw:space": "cosine"},
        )
        total = collection.count()
        if total == 0:
            return []

        model = get_embedding_model(self.settings.embedding_model)
        query_embedding = model.encode([query], normalize_embeddings=True).tolist()

        results = collection.query(
            query_embeddings=query_embedding,
            n_results=min(top_k, total),
            include=["documents", "metadatas", "distances"],
        )

        docs = results.get("documents", [[]])[0]
        metas = results.get("metadatas", [[]])[0]
        distances = results.get("distances", [[]])[0]

        matches: List[Dict[str, Any]] = []
        for doc, meta, dist in zip(docs, metas, distances):
            # Cosine distance in [0, 2]; similarity = 1 - dist
            relevance = round(max(0.0, min(1.0, 1.0 - float(dist))), 4)
            if relevance >= min_relevance:
                matches.append(
                    {
                        "runbook_name": meta.get("runbook_name", "unknown.md"),
                        "section_title": meta.get("section_title", ""),
                        "excerpt": doc,
                        "relevance_score": relevance,
                    }
                )
        return matches
