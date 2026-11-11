from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timezone
import json
from pathlib import Path
import statistics
import sys
import tempfile
import time
from uuid import uuid4

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.config import settings
from app.services.rag import IngestFileRef, RAGService


def _corpus_rows() -> list[dict[str, str]]:
    topics = [
        "water treatment", "coastal protection", "solar generation", "public transit",
        "food storage", "hospital backup", "school ventilation", "rural broadband",
    ]
    rows = []
    for index in range(24):
        topic = topics[index % len(topics)]
        rows.append(
            {
                "filename": f"assessment_{index + 1:02d}.txt",
                "topic": topic,
                "site": f"Zone {index + 1:02d}",
                "coefficient": f"{1.10 + (index * 0.07):.2f}",
            },
        )
    return rows


def _document(row: dict[str, str]) -> str:
    return (
        "Regional Infrastructure Readiness Assessment\n"
        f"This report evaluates {row['topic']} resilience at {row['site']}. "
        "The assessment uses the same reserve coefficient definition across sites. "
        f"The measured reserve coefficient at {row['site']} is {row['coefficient']}. "
        "The value is reported for planning comparisons and should not be transferred "
        "to another site's assessment."
    )


async def _run(output_root: Path, workspace: str) -> Path:
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    output = output_root / run_id
    output.mkdir(parents=True, exist_ok=True)
    workspace_id = workspace or f"scope-eval-{uuid4().hex[:10]}"
    rows = _corpus_rows()
    service = RAGService()
    measurements: list[dict[str, object]] = []

    try:
        with tempfile.TemporaryDirectory(prefix="insightedge-scope-") as temp_dir:
            refs = []
            for row in rows:
                path = Path(temp_dir) / row["filename"]
                path.write_text(_document(row), encoding="utf-8")
                refs.append(IngestFileRef(path=path, display_name=row["filename"]))
            ingest_started = time.perf_counter()
            ingest = await service.ingest_uploaded_files(refs, workspace_id=workspace_id)
            ingest_ms = round((time.perf_counter() - ingest_started) * 1000, 2)

        for row in rows:
            question = f"What reserve coefficient is reported in {row['filename']}?"
            resolved, selected, selector, _ = await service._resolve_document_scope(question, workspace_id)
            if not resolved or len(selected) != 1:
                measurements.append(
                    {
                        "filename": row["filename"],
                        "scope_resolved": False,
                        "scope_label": selector,
                        "baseline_sources": [],
                        "scoped_sources": [],
                    },
                )
                continue

            allowed_document_ids = {str(item.get("doc_id") or "") for item in selected}

            common = {
                "workspace_id": workspace_id,
                "retrieval_mode": "hybrid",
                "apply_compression": False,
                "candidate_k": 12,
                "final_top_k": 3,
                "use_hyde": False,
                "use_multi_query": False,
                "use_reranking": False,
                "use_parent_document": False,
                "model_name": settings.llm_model,
            }
            started = time.perf_counter()
            baseline = await service.retrieve_context(question, metadata_filter=None, **common)
            baseline_ms = round((time.perf_counter() - started) * 1000, 2)
            started = time.perf_counter()
            scoped = await service.retrieve_context(question, metadata_filter=resolved, **common)
            scoped_ms = round((time.perf_counter() - started) * 1000, 2)
            baseline_sources = [str(meta.get("filename") or meta.get("source")) for meta in baseline[1]]
            scoped_sources = [str(meta.get("filename") or meta.get("source")) for meta in scoped[1]]
            scoped_document_ids = {str(meta.get("document_id") or "") for meta in scoped[1]}
            scoped_citations = service._build_citations(scoped[1], scoped[2], scoped[0], scoped[3])
            retrieved_chunk_ids = set(scoped[2])
            retrieved_inside_scope = scoped_document_ids.issubset(allowed_document_ids)
            citations_inside_retrieved_evidence = all(
                citation.chunk_id in retrieved_chunk_ids
                and citation.document_id in allowed_document_ids
                for citation in scoped_citations
            )
            target = row["filename"]
            measurements.append(
                {
                    "filename": target,
                    "scope_resolved": True,
                    "baseline_sources": baseline_sources,
                    "scoped_sources": scoped_sources,
                    "allowed_document_ids": sorted(allowed_document_ids),
                    "scoped_document_ids": sorted(scoped_document_ids),
                    "baseline_target_hit": target in baseline_sources,
                    "scoped_target_hit": target in scoped_sources,
                    "baseline_leak_chunks": sum(source != target for source in baseline_sources),
                    "scoped_leak_chunks": sum(source != target for source in scoped_sources),
                    "retrieved_inside_scope": retrieved_inside_scope,
                    "citations_inside_retrieved_evidence": citations_inside_retrieved_evidence,
                    "scope_contract_pass": retrieved_inside_scope and citations_inside_retrieved_evidence,
                    "baseline_latency_ms": baseline_ms,
                    "scoped_latency_ms": scoped_ms,
                },
            )

        valid = [item for item in measurements if item.get("scope_resolved")]
        total_baseline_chunks = sum(len(item["baseline_sources"]) for item in valid)
        total_scoped_chunks = sum(len(item["scoped_sources"]) for item in valid)
        payload = {
            "run_id": run_id,
            "workspace": workspace_id,
            "benchmark": "near-duplicate named-document scope stress test",
            "corpus": rows,
            "ingestion": {
                "files_processed": ingest.files_processed,
                "chunks_indexed": ingest.chunks_indexed,
                "ingestion_ms": ingest_ms,
            },
            "configuration": {
                "retrieval_mode": "hybrid",
                "candidate_k": 12,
                "final_top_k": 3,
                "embedding_provider": settings.embedding_provider,
                "embedding_model": settings.embedding_model,
                "generation_enabled": False,
            },
            "metrics": {
                "queries": len(rows),
                "scope_resolution_rate": len(valid) / len(rows),
                "baseline_target_recall_at_3": sum(bool(i.get("baseline_target_hit")) for i in valid) / len(valid),
                "scoped_target_recall_at_3": sum(bool(i.get("scoped_target_hit")) for i in valid) / len(valid),
                "baseline_out_of_scope_chunk_rate": sum(int(i.get("baseline_leak_chunks", 0)) for i in valid) / max(1, total_baseline_chunks),
                "scoped_out_of_scope_chunk_rate": sum(int(i.get("scoped_leak_chunks", 0)) for i in valid) / max(1, total_scoped_chunks),
                "scope_contract_pass_rate": sum(bool(i.get("scope_contract_pass")) for i in valid) / max(1, len(valid)),
                "baseline_mean_latency_ms": statistics.mean(float(i["baseline_latency_ms"]) for i in valid),
                "scoped_mean_latency_ms": statistics.mean(float(i["scoped_latency_ms"]) for i in valid),
            },
            "results": measurements,
        }
        (output / "results.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
        metrics = payload["metrics"]
        summary = [
            "# Document Scope Contract Evaluation",
            "",
            f"- Run ID: {run_id}",
            f"- Synthetic near-duplicate documents: {len(rows)}",
            f"- Queries: {len(rows)} filename-scoped factual lookups",
            f"- Ingestion: {ingest.files_processed} files, {ingest.chunks_indexed} chunks, {ingest_ms:.2f} ms total",
            "- Comparison: ordinary hybrid top-3 retrieval versus the same retrieval with filename-resolved document-ID filtering",
            "- Generation: disabled; this isolates retrieval and source-scope behavior",
            "",
            "| Metric | Unscoped retrieval | Scope constrained |",
            "| --- | ---: | ---: |",
            f"| Target document recall@3 | {metrics['baseline_target_recall_at_3']:.3f} | {metrics['scoped_target_recall_at_3']:.3f} |",
            f"| Out-of-scope chunk rate | {metrics['baseline_out_of_scope_chunk_rate']:.3f} | {metrics['scoped_out_of_scope_chunk_rate']:.3f} |",
            f"| Scope contract pass rate | n/a | {metrics['scope_contract_pass_rate']:.3f} |",
            f"| Mean retrieval latency (ms) | {metrics['baseline_mean_latency_ms']:.2f} | {metrics['scoped_mean_latency_ms']:.2f} |",
            f"| Scope resolution rate | n/a | {metrics['scope_resolution_rate']:.3f} |",
            "",
            "The generated corpus intentionally uses near-duplicate reports with the same vocabulary and source-specific measurements. Results characterize this controlled stress test only; they do not estimate leakage rates for arbitrary user documents.",
        ]
        (output / "summary.md").write_text("\n".join(summary) + "\n", encoding="utf-8")
    finally:
        service.delete_workspace(workspace_id)
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate document-scope filtering on near-duplicate local reports.")
    parser.add_argument("--output-root", default=str(BACKEND_DIR / "data" / "eval_scope_runs"))
    parser.add_argument("--workspace", default="")
    args = parser.parse_args()
    output = asyncio.run(_run(Path(args.output_root), args.workspace))
    print(f"Scope evaluation artifacts written to {output}")


if __name__ == "__main__":
    main()
