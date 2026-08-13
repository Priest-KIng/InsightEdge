import argparse
import asyncio
import json

from app.schemas import Citation
from app.services.rag import IngestStats
import scripts.evaluate_rag as evaluate_rag


class FakeRAGService:
    def delete_workspace(self, workspace: str) -> None:
        return None

    async def ingest_uploaded_files(self, files, workspace_id=None) -> IngestStats:
        return IngestStats(files_processed=1, chunks_indexed=1, skipped_files=0)

    async def retrieve_context(self, question, **kwargs):
        if "lunar" in question.lower():
            return [], [], [], []
        filename = "table.md" if "table" in question.lower() else "prose.txt"
        if "ocr" in question.lower() or "phrase" in question.lower():
            filename = "ocr_marker.txt"
        if "provenance" in question.lower():
            filename = "citation_rich.md"
        return ["ChromaDB SQLite blue ledger total document ID chunk ID retrieval rank"], [
            {"filename": filename, "document_id": "doc", "snippet": "blue ledger total"},
        ], ["doc:0"], [0.1]

    @staticmethod
    def _build_citations(metadatas, ids, documents, distances):
        return [
            Citation(
                source=str(metadata["filename"]),
                filename=str(metadata["filename"]),
                chunk_id=ids[index],
                snippet=documents[index],
                score=1 / (1 + distances[index]),
            )
            for index, metadata in enumerate(metadatas)
        ]


def test_benchmark_smoke_writes_all_artifacts(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(evaluate_rag, "RAGService", FakeRAGService)
    monkeypatch.setattr(
        evaluate_rag,
        "_fixture_files",
        lambda: [evaluate_rag.IngestFileRef(path=tmp_path / "fixture.txt", display_name="prose.txt")],
    )
    monkeypatch.setattr(
        evaluate_rag,
        "_load_questions",
        lambda: [
            {
                "id": "smoke",
                "question": "Where is the table?",
                "expected_sources": ["prose.txt"],
                "required_terms": ["ChromaDB"],
            },
        ],
    )
    args = argparse.Namespace(
        output_root=str(tmp_path / "runs"),
        workspace="smoke",
        modes="hybrid,router",
        retrieval_router=True,
        model_router=True,
        hyde=False,
        multi_query=False,
        reranking=False,
        compression=False,
        parent_document=False,
    )

    output_dir = asyncio.run(evaluate_rag._run(args))

    assert (output_dir / "results.json").exists()
    assert (output_dir / "metrics.csv").exists()
    assert (output_dir / "summary.md").exists()
    payload = json.loads((output_dir / "results.json").read_text(encoding="utf-8"))
    assert payload["rows"]
