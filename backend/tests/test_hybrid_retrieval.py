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


def test_document_overview_retrieval_preserves_explicit_source_scope():
    class ScopedVectorStore:
        def get_all(self, workspace_id):
            return {
                "ids": ["river", "harbor", "food"],
                "documents": ["River plan", "Harbor plan", "Food plan"],
                "metadatas": [
                    {"document_id": "river", "filename": "river.txt", "chunk_index": 0},
                    {"document_id": "harbor", "filename": "harbor.txt", "chunk_index": 0},
                    {"document_id": "food", "filename": "food.txt", "chunk_index": 0},
                ],
            }

    service = RAGService.__new__(RAGService)
    service.vectordb = ScopedVectorStore()
    documents, metadatas, ids, _ = asyncio.run(
        service.retrieve_context(
            "Summarize river.txt",
            workspace_id="test",
            retrieval_mode="dense",
            apply_compression=False,
            final_top_k=6,
            metadata_filter={"document_id": "river"},
        ),
    )

    assert ids == ["river"]
    assert documents == ["River plan"]
    assert [metadata["filename"] for metadata in metadatas] == ["river.txt"]


def test_multi_document_overview_covers_distinct_documents():
    class MultiFileVectorStore:
        def get_all(self, workspace_id):
            documents = [
                f"Project overview: shared requirements and milestones, section {index}."
                for index in range(6)
            ]
            documents.append("Project overview: risks and milestones across partner files.")
            return {
                "ids": [f"a-{index}" for index in range(6)] + ["b-0"],
                "documents": documents,
                "metadatas": [
                    {"document_id": "doc-a", "filename": "a.txt", "chunk_index": index}
                    for index in range(6)
                ] + [{"document_id": "doc-b", "filename": "b.txt", "chunk_index": 0}],
            }

    service = RAGService.__new__(RAGService)
    service.vectordb = MultiFileVectorStore()
    service.embedder = FakeEmbedder()
    service.reranker = None

    _, metadatas, ids, _ = asyncio.run(
        service.retrieve_context(
            "Summarize all documents",
            workspace_id="test",
            retrieval_mode="lexical",
            candidate_k=10,
            final_top_k=3,
            apply_compression=False,
            use_hyde=False,
            use_multi_query=False,
            use_parent_document=False,
        ),
    )

    assert len(ids) == 3
    assert [metadata["document_id"] for metadata in metadatas] == ["doc-a", "doc-a", "doc-b"]


def test_source_coverage_indices_prioritize_distinct_documents():
    metadata = [
        {"document_id": "doc-a"},
        {"document_id": "doc-a"},
        {"document_id": "doc-b"},
        {"document_id": "doc-c"},
    ]

    selected = RAGService._source_coverage_indices(metadata, limit=3, rank_window=3)

    assert selected == [0, 1, 2]


def test_bounded_source_coverage_uses_near_top_alternative_and_preserves_order():
    metadata = [
        {"document_id": "doc-a"},
        {"document_id": "doc-a"},
        {"document_id": "doc-a"},
        {"document_id": "doc-b"},
        {"document_id": "doc-c"},
    ]

    selected = RAGService._source_coverage_indices(metadata, limit=3, rank_window=2)

    assert selected == [0, 1, 3]


def test_zero_source_coverage_window_keeps_original_top_k():
    metadata = [
        {"document_id": "doc-a"},
        {"document_id": "doc-a"},
        {"document_id": "doc-a"},
        {"document_id": "doc-b"},
    ]

    selected = RAGService._source_coverage_indices(metadata, limit=3, rank_window=0)

    assert selected == [0, 1, 2]


def test_multi_source_query_uses_near_top_document_candidate_in_retrieval_path():
    class MultiFileVectorStore:
        def get_all(self, workspace_id):
            documents = [
                f"Compare annual retention plans across reports; approved policy values are in this report, section {index}."
                for index in range(6)
            ]
            documents.append("Annual retention contracts are archived in all secondary reports.")
            return {
                "ids": [f"a-{index}" for index in range(6)] + ["b-0"],
                "documents": documents,
                "metadatas": [
                    {"document_id": "doc-a", "filename": "a.txt", "chunk_index": index}
                    for index in range(6)
                ] + [{"document_id": "doc-b", "filename": "b.txt", "chunk_index": 0}],
            }

    service = RAGService.__new__(RAGService)
    service.vectordb = MultiFileVectorStore()
    service.embedder = FakeEmbedder()
    service.reranker = None

    _, metadatas, ids, _ = asyncio.run(
        service.retrieve_context(
            "Compare annual retention plans across reports",
            workspace_id="test",
            retrieval_mode="lexical",
            candidate_k=10,
            final_top_k=3,
            apply_compression=False,
            use_hyde=False,
            use_multi_query=False,
            use_parent_document=False,
        ),
    )

    assert len(ids) == 3
    assert [metadata["document_id"] for metadata in metadatas] == ["doc-a", "doc-a", "doc-b"]
