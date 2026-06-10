from __future__ import annotations

import argparse
import asyncio
import csv
import json
import math
import statistics
import sys
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.config import BACKEND_DIR
from app.services.rag import IngestFileRef, RAGService


FIXTURE_DIR = BACKEND_DIR / "eval" / "fixtures"
DOCUMENT_DIR = FIXTURE_DIR / "documents"
QUESTION_FILE = FIXTURE_DIR / "questions.json"
OUTPUT_ROOT = BACKEND_DIR / "data" / "eval_runs"


@dataclass
class QueryResult:
    mode: str
    question_id: str
    question: str
    expected_sources: list[str]
    retrieved_sources: list[str]
    recall_at_k: float
    mrr: float
    ndcg_at_k: float
    context_precision: float
    context_recall: float
    citation_precision: float
    groundedness: float
    query_latency_ms: float
    retrieved_chunks: int


def _load_questions() -> list[dict[str, object]]:
    return json.loads(QUESTION_FILE.read_text(encoding="utf-8"))


def _fixture_files() -> list[IngestFileRef]:
    return [
        IngestFileRef(path=path, display_name=path.name)
        for path in sorted(DOCUMENT_DIR.iterdir())
        if path.is_file()
    ]


def _dcg(relevance: list[int]) -> float:
    return sum(value / math.log2(index + 2) for index, value in enumerate(relevance))


def _retrieval_metrics(expected_sources: list[str], retrieved_sources: list[str]) -> tuple[float, float, float, float, float]:
    expected = set(expected_sources)
    if not expected:
        return 0.0, 0.0, 0.0, 0.0, 0.0
    hits = [1 if source in expected else 0 for source in retrieved_sources]
    recall = 1.0 if any(hits) else 0.0
    reciprocal_rank = 0.0
    for index, hit in enumerate(hits, start=1):
        if hit:
            reciprocal_rank = 1.0 / index
            break
    ideal = sorted(hits, reverse=True)
    ndcg = (_dcg(hits) / _dcg(ideal)) if any(ideal) else 0.0
    precision = sum(hits) / len(hits) if hits else 0.0
    context_recall = min(1.0, len(set(retrieved_sources).intersection(expected)) / len(expected))
    return recall, reciprocal_rank, ndcg, precision, context_recall


def _groundedness(required_terms: list[str], context_text: str) -> float:
    if not required_terms:
        return 0.0
    lowered = context_text.lower()
    hits = sum(1 for term in required_terms if term.lower() in lowered)
    return hits / len(required_terms)


def _percentile(values: list[float], percentile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, math.ceil((percentile / 100) * len(ordered)) - 1))
    return ordered[index]


async def _run(args: argparse.Namespace) -> Path:
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    output_dir = OUTPUT_ROOT / run_id
    output_dir.mkdir(parents=True, exist_ok=True)
    workspace = args.workspace or f"eval-{uuid4().hex[:10]}"
    modes = args.modes.split(",") if args.modes else ["dense", "lexical", "hybrid", "hybrid_compression"]

    service = RAGService()
    service.delete_workspace(workspace)

    ingest_started = time.perf_counter()
    stats = await service.ingest_uploaded_files(_fixture_files(), workspace_id=workspace)
    ingest_latency_ms = round((time.perf_counter() - ingest_started) * 1000, 2)
    ingestion_success = 1.0 if stats.files_processed == len(_fixture_files()) and stats.chunks_indexed > 0 else 0.0

    rows: list[QueryResult] = []
    questions = _load_questions()
    for mode in modes:
        retrieval_mode = {
            "dense": "dense",
            "dense-only": "dense",
            "lexical": "lexical",
            "hybrid": "hybrid",
            "hybrid_compression": "hybrid_compression",
            "hybrid+compression": "hybrid_compression",
            "hybrid_rerank": "hybrid_rerank",
            "hybrid+reranker": "hybrid_rerank",
        }.get(mode.strip(), mode.strip())
        for question in questions:
            started = time.perf_counter()
            documents, metadatas, _, distances = await service.retrieve_context(
                str(question["question"]),
                workspace_id=workspace,
                retrieval_mode=retrieval_mode,
                apply_compression=retrieval_mode == "hybrid_compression",
            )
            latency_ms = round((time.perf_counter() - started) * 1000, 2)
            retrieved_sources = [
                str(metadata.get("filename") or metadata.get("source") or "unknown")
                for metadata in metadatas
            ]
            expected_sources = [str(item) for item in question.get("expected_sources", [])]
            required_terms = [str(item) for item in question.get("required_terms", [])]
            recall, mrr, ndcg, precision, context_recall = _retrieval_metrics(expected_sources, retrieved_sources)
            citations = service._build_citations(metadatas, documents, distances)
            citation_sources = [citation.filename or citation.source for citation in citations]
            citation_precision = (
                sum(1 for source in citation_sources if source in set(expected_sources)) / len(citation_sources)
                if citation_sources
                else 0.0
            )
            rows.append(
                QueryResult(
                    mode=retrieval_mode,
                    question_id=str(question["id"]),
                    question=str(question["question"]),
                    expected_sources=expected_sources,
                    retrieved_sources=retrieved_sources,
                    recall_at_k=recall,
                    mrr=mrr,
                    ndcg_at_k=ndcg,
                    context_precision=precision,
                    context_recall=context_recall,
                    citation_precision=citation_precision,
                    groundedness=_groundedness(required_terms, "\n".join(documents)),
                    query_latency_ms=latency_ms,
                    retrieved_chunks=len(documents),
                )
            )

    result_payload = {
        "run_id": run_id,
        "workspace": workspace,
        "fixture_documents": [file.display_name for file in _fixture_files()],
        "ingest": {
            "files_processed": stats.files_processed,
            "chunks_indexed": stats.chunks_indexed,
            "skipped_files": stats.skipped_files,
            "latency_ms": ingest_latency_ms,
            "success_rate": ingestion_success,
            "ocr_marker_rate": 1 / len(_fixture_files()),
        },
        "rows": [asdict(row) for row in rows],
    }
    (output_dir / "results.json").write_text(json.dumps(result_payload, indent=2), encoding="utf-8")

    with (output_dir / "metrics.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(asdict(rows[0]).keys()))
        writer.writeheader()
        for row in rows:
            writer.writerow(asdict(row))

    grouped: dict[str, list[QueryResult]] = {}
    for row in rows:
        grouped.setdefault(row.mode, []).append(row)

    lines = [
        "# InsightEdge Local RAG Evaluation",
        "",
        f"- Run ID: `{run_id}`",
        f"- Workspace: `{workspace}`",
        f"- Fixture documents: {len(_fixture_files())}",
        f"- Ingestion success rate: {ingestion_success:.3f}",
        f"- Ingestion latency: {ingest_latency_ms:.2f} ms",
        "",
        "## Retrieval Baselines",
        "",
        "| Mode | Recall@k | MRR | nDCG@k | Context Precision | Context Recall | Citation Precision | Groundedness | P50 Query ms | P95 Query ms |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for mode, mode_rows in grouped.items():
        latencies = [row.query_latency_ms for row in mode_rows]
        lines.append(
            "| "
            + " | ".join(
                [
                    mode,
                    f"{statistics.mean(row.recall_at_k for row in mode_rows):.3f}",
                    f"{statistics.mean(row.mrr for row in mode_rows):.3f}",
                    f"{statistics.mean(row.ndcg_at_k for row in mode_rows):.3f}",
                    f"{statistics.mean(row.context_precision for row in mode_rows):.3f}",
                    f"{statistics.mean(row.context_recall for row in mode_rows):.3f}",
                    f"{statistics.mean(row.citation_precision for row in mode_rows):.3f}",
                    f"{statistics.mean(row.groundedness for row in mode_rows):.3f}",
                    f"{_percentile(latencies, 50):.2f}",
                    f"{_percentile(latencies, 95):.2f}",
                ]
            )
            + " |"
        )
    lines.extend(
        [
            "",
            "## Notes",
            "",
            "- This fixture benchmark is intentionally small and local; it supports regression testing and report evidence, not broad claims of state-of-the-art performance.",
            "- Groundedness is a deterministic required-term heuristic over retrieved context, not a human or LLM judge.",
            "- OCR success is represented by an OCR marker fixture because external OCR binaries are environment-dependent.",
        ]
    )
    (output_dir / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return output_dir


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the local InsightEdge RAG fixture benchmark.")
    parser.add_argument("--preset", default="quick", choices=["quick"])
    parser.add_argument("--workspace", default="")
    parser.add_argument("--modes", default="")
    args = parser.parse_args()
    output_dir = asyncio.run(_run(args))
    print(f"Evaluation artifacts written to {output_dir}")


if __name__ == "__main__":
    main()
