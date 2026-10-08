from __future__ import annotations

import asyncio

import pytest

from app.services.rag import RAGService


class FakeVectorStore:
    def get_all(self, workspace_id):
        return {
            "ids": ["exact", "semantic"],
            "documents": [
                "The Zephyr protocol assigns project code QX-417 to the archive migration.",
                "A different migration plan uses a staged archive transfer.",
            ],
            "metadatas": [{"filename": "exact.md"}, {"filename": "semantic.md"}],
        }

    def query(self, embedding, top_k, workspace_id, metadata_filter):
        # Simulate vector search missing the exact identifier entirely.
        return {
            "ids": [["semantic"]],
            "documents": [["A different migration plan uses a staged archive transfer."]],
            "metadatas": [[{"filename": "semantic.md"}]],
            "distances": [[0.2]],
        }


class FakeEmbedder:
    def embed(self, texts):
        return [[0.0, 1.0] for _ in texts]


def test_hybrid_retrieval_recovers_exact_match_outside_dense_candidates():
    service = RAGService.__new__(RAGService)
    service.vectordb = FakeVectorStore()
    service.embedder = FakeEmbedder()
    service.reranker = None

    documents, metadatas, ids, _ = asyncio.run(service.retrieve_context(
        "Which project code belongs to the Zephyr protocol?",
        workspace_id="test",
        retrieval_mode="hybrid",
        apply_compression=False,
        candidate_k=2,
        final_top_k=2,
        use_hyde=False,
        use_multi_query=False,
        use_parent_document=False,
    ))

    assert "exact" in ids
    assert documents[ids.index("exact")].startswith("The Zephyr protocol")
    assert metadatas[ids.index("exact")]["filename"] == "exact.md"


def test_lexical_retrieval_applies_metadata_filter():
    service = RAGService.__new__(RAGService)
    service.vectordb = FakeVectorStore()
    service.embedder = FakeEmbedder()
    service.reranker = None

    _, metadatas, ids, _ = asyncio.run(service.retrieve_context(
        "Zephyr protocol project code",
        workspace_id="test",
        retrieval_mode="lexical",
        apply_compression=False,
        final_top_k=3,
        metadata_filter={"filename": "exact.md"},
        use_hyde=False,
        use_multi_query=False,
        use_parent_document=False,
    ))

    assert ids == ["exact"]
    assert metadatas[0]["filename"] == "exact.md"
