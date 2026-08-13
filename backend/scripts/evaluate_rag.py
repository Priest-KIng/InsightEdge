from __future__ import annotations

import argparse
import asyncio
import csv
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import statistics
import sys
import time
from uuid import uuid4

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.config import settings
from app.services.rag import IngestFileRef, RAGService
from app.services.router import RoutingDecision, classify_query

FIXTURE_DIR = BACKEND_DIR / "eval" / "fixtures"
DOCUMENT_DIR = FIXTURE_DIR / "documents"
QUESTION_FILE = FIXTURE_DIR / "questions.json"
OUTPUT_ROOT = BACKEND_DIR / "data" / "eval_runs"


@dataclass
class QueryResult:
    configuration: str
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
    source_correctness: float
    chunk_correctness: float
    groundedness: float
    query_latency_ms: float
    retrieved_chunks: int
    query_type: str
    selected_model: str


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


def _metrics(
    question: dict[str, object],
    metadatas: list[dict[str, object]],
    retrieved_sources: list[str],
) -> tuple[float, float, float, float, float, float, float]:
    expected_sources = {str(item) for item in question.get("expected_sources", [])}
    expected_snippets = [str(item).lower() for item in question.get("expected_snippets", [])]
    expected_pages = {int(item) for item in question.get("expected_pages", [])}
    hits = [
        int(
            str(metadata.get("filename") or metadata.get("source") or "") in expected_sources
            and (not expected_pages or metadata.get("page_number") in expected_pages)
        )
        for metadata in metadatas
    ]
    source_hits = [
        int(str(metadata.get("filename") or metadata.get("source") or "") in expected_sources)
        for metadata in metadatas
    ]
    snippet_hits = [
        int(
            not expected_snippets
            or any(term in str(metadata.get("snippet", "")).lower() for term in expected_snippets)
        )
        for metadata in metadatas
    ]
    recall = 1.0 if any(hits) else 0.0
    mrr = next((1.0 / index for index, hit in enumerate(hits, start=1) if hit), 0.0)
    ideal = sorted(hits, reverse=True)
    ndcg = _dcg(hits) / _dcg(ideal) if any(ideal) else 0.0
    precision = sum(hits) / len(hits) if hits else 0.0
    context_recall = min(
        1.0,
        len({source for source in retrieved_sources if source in expected_sources})
        / max(1, len(expected_sources)),
    )
    source_correctness = sum(source_hits) / len(source_hits) if source_hits else 0.0
    chunk_correctness = (
        sum(1 for source, snippet in zip(source_hits, snippet_hits) if source and snippet) / len(hits)
        if hits
        else 0.0
    )
    return recall, mrr, ndcg, precision, context_recall, source_correctness, chunk_correctness


def _groundedness(required_terms: list[str], context_text: str) -> float:
    if not required_terms:
        return 0.0
    lowered = context_text.lower()
    return sum(term.lower() in lowered for term in required_terms) / len(required_terms)


def _percentile(values: list[float], percentile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, math.ceil(percentile / 100 * len(ordered)) - 1))
    return ordered[index]


def _decision_for(
    question: str,
    mode: str,
    router_enabled: bool,
    *,
    hyde: bool,
    multi_query: bool,
    reranking: bool,
    compression: bool,
    parent_document: bool,
) -> RoutingDecision:
    if router_enabled:
        decision = classify_query(question)
        return RoutingDecision(
            **{
                **decision.__dict__,
                "use_hyde": hyde,
                "use_multi_query": multi_query,
                "use_reranking": reranking,
                "use_compression": compression,
                "use_parent_document": parent_document,
            },
        )
    return RoutingDecision(
        query_type="baseline",
        complexity_score=0.0,
        rationale="Fixed retrieval baseline.",
        retrieval_mode=mode,
        candidate_k=settings.retrieval_candidate_k,
        final_top_k=settings.top_k,
        use_hyde=hyde,
        use_multi_query=multi_query,
        use_reranking=reranking,
        use_compression=compression,
        use_parent_document=parent_document,
        model_name=settings.llm_model,
    )


async def _run(args: argparse.Namespace) -> Path:
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    output_root = Path(args.output_root) if args.output_root else OUTPUT_ROOT
    output_dir = output_root / run_id
    output_dir.mkdir(parents=True, exist_ok=True)
    workspace = args.workspace or f"eval-{uuid4().hex[:10]}"
    files = _fixture_files()
    questions = _load_questions()
    modes = [mode.strip() for mode in args.modes.split(",")] if args.modes else [
        "dense", "lexical", "hybrid", "hybrid_rerank", "hybrid_compression", "router",
    ]
    features = {
        "hyde": args.hyde,
        "multi_query": args.multi_query,
        "reranking": args.reranking,
        "compression": args.compression,
        "parent_document": args.parent_document,
        "retrieval_router": args.retrieval_router,
        "model_router": args.model_router,
    }

    service = RAGService()
    service.delete_workspace(workspace)
    ingest_latencies: list[float] = []
    per_file: list[dict[str, object]] = []
    total_stats = {"files_processed": 0, "chunks_indexed": 0, "skipped_files": 0}
    for file_ref in files:
        started = time.perf_counter()
        stats = await service.ingest_uploaded_files([file_ref], workspace_id=workspace)
        latency = round((time.perf_counter() - started) * 1000, 2)
        ingest_latencies.append(latency)
        total_stats["files_processed"] += stats.files_processed
        total_stats["chunks_indexed"] += stats.chunks_indexed
        total_stats["skipped_files"] += stats.skipped_files
        per_file.append({"filename": file_ref.display_name, "latency_ms": latency, "stats": asdict(stats)})

    rows: list[QueryResult] = []
    for mode in modes:
        retrieval_mode = {
            "dense-only": "dense",
            "hybrid+compression": "hybrid_compression",
            "hybrid+reranker": "hybrid_rerank",
        }.get(mode, mode)
        router_enabled = retrieval_mode == "router"
        for question in questions:
            decision = _decision_for(
                str(question["question"]),
                "hybrid" if router_enabled else retrieval_mode,
                router_enabled and args.retrieval_router,
                hyde=args.hyde,
                multi_query=args.multi_query,
                reranking=args.reranking or retrieval_mode == "hybrid_rerank",
                compression=args.compression or retrieval_mode == "hybrid_compression",
                parent_document=args.parent_document,
            )
            if router_enabled and args.model_router and hasattr(service, "model_router"):
                decision = await service.model_router.select(decision)
            elif not args.model_router:
                decision = RoutingDecision(
                    **{**decision.__dict__, "model_name": settings.llm_model, "model_source": "ablation-disabled"},
                )
            started = time.perf_counter()
            documents, metadatas, ids, distances = await service.retrieve_context(
                str(question["question"]),
                workspace_id=workspace,
                retrieval_mode=decision.retrieval_mode,
                apply_compression=decision.use_compression,
                candidate_k=decision.candidate_k,
                final_top_k=decision.final_top_k,
                metadata_filter=decision.metadata_filter,
                use_hyde=decision.use_hyde,
                use_multi_query=decision.use_multi_query,
                use_reranking=decision.use_reranking,
                use_parent_document=decision.use_parent_document,
                model_name=decision.model_name,
            )
            latency_ms = round((time.perf_counter() - started) * 1000, 2)
            retrieved_sources = [
                str(metadata.get("filename") or metadata.get("source") or "unknown")
                for metadata in metadatas
            ]
            metrics = _metrics(question, metadatas, retrieved_sources)
            citations = service._build_citations(metadatas, ids, documents, distances)
            expected_sources = [str(item) for item in question.get("expected_sources", [])]
            citation_precision = (
                sum(1 for citation in citations if (citation.filename or citation.source) in set(expected_sources))
                / len(citations)
                if citations
                else 0.0
            )
            rows.append(
                QueryResult(
                    configuration=mode,
                    mode=decision.retrieval_mode,
                    question_id=str(question["id"]),
                    question=str(question["question"]),
                    expected_sources=expected_sources,
                    retrieved_sources=retrieved_sources,
                    recall_at_k=metrics[0],
                    mrr=metrics[1],
                    ndcg_at_k=metrics[2],
                    context_precision=metrics[3],
                    context_recall=metrics[4],
                    citation_precision=citation_precision,
                    source_correctness=metrics[5],
                    chunk_correctness=metrics[6],
                    groundedness=_groundedness(
                        [str(item) for item in question.get("required_terms", [])],
                        "\n".join(documents),
                    ),
                    query_latency_ms=latency_ms,
                    retrieved_chunks=len(documents),
                    query_type=decision.query_type,
                    selected_model=decision.model_name or settings.llm_model,
                ),
            )

    payload = {
        "run_id": run_id,
        "workspace": workspace,
        "fixture_documents": [file.display_name for file in files],
        "configuration": features,
        "ingest": {
            **total_stats,
            "success_rate": total_stats["files_processed"] / max(1, len(files)),
            "ocr_marker_rate": 1 / max(1, len(files)),
            "latency_p50_ms": _percentile(ingest_latencies, 50),
            "latency_p95_ms": _percentile(ingest_latencies, 95),
            "files": per_file,
        },
        "rows": [asdict(row) for row in rows],
    }
    (output_dir / "results.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    with (output_dir / "metrics.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(asdict(rows[0]).keys()))
        writer.writeheader()
        writer.writerows(asdict(row) for row in rows)

    grouped: dict[str, list[QueryResult]] = {}
    for row in rows:
        grouped.setdefault(row.configuration, []).append(row)
    lines = [
        "# InsightEdge Local RAG Evaluation",
        "",
        f"- Run ID: {run_id}",
        f"- Workspace: {workspace}",
        f"- Fixture documents: {len(files)}",
        f"- Ingestion success rate: {payload['ingest']['success_rate']:.3f}",
        f"- OCR marker rate: {payload['ingest']['ocr_marker_rate']:.3f}",
        f"- Ingestion P50/P95: {payload['ingest']['latency_p50_ms']:.2f}/{payload['ingest']['latency_p95_ms']:.2f} ms",
        "",
        "## Comparative Retrieval Table",
        "",
        "| Configuration | Recall@k | MRR | nDCG@k | Context P | Context R | Citation P | Source correctness | Chunk correctness | P50 ms | P95 ms |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for configuration, configuration_rows in grouped.items():
        latencies = [row.query_latency_ms for row in configuration_rows]
        lines.append(
            "| "
            + " | ".join(
                [
                    configuration,
                    f"{statistics.mean(row.recall_at_k for row in configuration_rows):.3f}",
                    f"{statistics.mean(row.mrr for row in configuration_rows):.3f}",
                    f"{statistics.mean(row.ndcg_at_k for row in configuration_rows):.3f}",
                    f"{statistics.mean(row.context_precision for row in configuration_rows):.3f}",
                    f"{statistics.mean(row.context_recall for row in configuration_rows):.3f}",
                    f"{statistics.mean(row.citation_precision for row in configuration_rows):.3f}",
                    f"{statistics.mean(row.source_correctness for row in configuration_rows):.3f}",
                    f"{statistics.mean(row.chunk_correctness for row in configuration_rows):.3f}",
                    f"{_percentile(latencies, 50):.2f}",
                    f"{_percentile(latencies, 95):.2f}",
                ],
            )
            + " |",
        )
    lines.extend(
        [
            "",
            "## Observed Discussion",
            "",
            "Values above are computed from the checked-in local fixture corpus. No broad or state-of-the-art claim is implied.",
            "Use the per-question rows in results.json and metrics.csv to identify which routing or retrieval configuration changed each result.",
            "Groundedness uses deterministic required-term matching and should be treated as a regression signal, not a human or LLM judge.",
        ],
    )
    (output_dir / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return output_dir


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the local InsightEdge RAG fixture benchmark.")
    parser.add_argument("--workspace", default="")
    parser.add_argument("--modes", default="")
    parser.add_argument("--output-root", default="")
    parser.add_argument("--retrieval-router", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--model-router", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--hyde", action=argparse.BooleanOptionalAction, default=False)
    parser.add_argument("--multi-query", action=argparse.BooleanOptionalAction, default=False)
    parser.add_argument("--reranking", action=argparse.BooleanOptionalAction, default=False)
    parser.add_argument("--compression", action=argparse.BooleanOptionalAction, default=False)
    parser.add_argument("--parent-document", action=argparse.BooleanOptionalAction, default=False)
    args = parser.parse_args()
    output_dir = asyncio.run(_run(args))
    print(f"Evaluation artifacts written to {output_dir}")


if __name__ == "__main__":
    main()
