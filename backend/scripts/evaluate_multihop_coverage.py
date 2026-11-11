from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import sqlite3
import statistics
import sys
import time
from typing import Any

import numpy as np

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))
SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from app.services.chunker import chunk_text
from app.services.router import is_multi_source_query
from evaluate_enterprise_coverage import (
    _query_terms,
    _select_bounded_source_cap,
    _select_relevance_gated_source_cap,
    _select_unique_sources,
)

SEED = 20261112
BOOTSTRAP_SAMPLES = 5000
TOP_K = 8
CANDIDATE_K = 100


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _build_index(corpus_path: Path, database_path: Path) -> dict[str, Any]:
    corpus = json.loads(corpus_path.read_text(encoding="utf-8"))
    if not isinstance(corpus, list) or not corpus:
        raise ValueError("MultiHop-RAG corpus must be a non-empty JSON list")
    database_path.parent.mkdir(parents=True, exist_ok=True)
    if database_path.exists():
        database_path.unlink()
    connection = sqlite3.connect(database_path)
    try:
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA synchronous=NORMAL")
        connection.execute(
            "CREATE VIRTUAL TABLE chunks USING fts5("
            "document_id UNINDEXED, title UNINDEXED, chunk_index UNINDEXED, content, "
            "tokenize='unicode61 remove_diacritics 2')",
        )
        rows: list[tuple[str, str, int, str]] = []
        seen_titles: set[str] = set()
        for article in corpus:
            title = str(article.get("title") or "").strip()
            if not title:
                continue
            key = title.casefold()
            if key in seen_titles:
                raise ValueError(f"Duplicate article title prevents gold-source mapping: {title!r}")
            seen_titles.add(key)
            text = f"{title}\n{article.get('body') or ''}".strip()
            for chunk_index, chunk in enumerate(chunk_text(text, chunk_size=1400, chunk_overlap=280)):
                rows.append((title, title, chunk_index, chunk))
        connection.executemany(
            "INSERT INTO chunks(document_id,title,chunk_index,content) VALUES (?,?,?,?)",
            rows,
        )
        connection.execute("INSERT INTO chunks(chunks) VALUES ('optimize')")
        connection.commit()
        return {"document_count": len(seen_titles), "chunk_count": len(rows)}
    finally:
        connection.close()


def _retrieve(connection: sqlite3.Connection, query: str) -> list[dict[str, Any]]:
    terms = list(dict.fromkeys(_query_terms(query)))
    if not terms:
        return []
    match = " OR ".join(f'"{term.replace(chr(34), "")}"' for term in terms)
    rows = connection.execute(
        "SELECT document_id,title,chunk_index,content,bm25(chunks) AS score "
        "FROM chunks WHERE chunks MATCH ? ORDER BY score LIMIT ?",
        (match, CANDIDATE_K),
    ).fetchall()
    return [
        {
            "document_id": str(row[0]),
            "title": str(row[1]),
            "chunk_index": int(row[2]),
            "content": str(row[3]),
            "score": float(row[4]),
        }
        for row in rows
    ]


def _mmr_select(
    candidates: list[dict[str, Any]],
    top_k: int,
    relevance_weight: float,
) -> list[dict[str, Any]]:
    """Lexical MMR baseline: normalized BM25 relevance minus token-set overlap."""
    if not candidates or top_k <= 0:
        return []
    strengths = [max(0.0, -float(row["score"])) for row in candidates]
    low, high = min(strengths), max(strengths)
    scale = max(1e-12, high - low)
    relevance = [(value - low) / scale for value in strengths]
    term_sets = [set(re.findall(r"[a-z0-9_]+", str(row["content"]).casefold())) for row in candidates]
    selected: list[int] = []
    remaining = set(range(len(candidates)))
    while remaining and len(selected) < top_k:
        best_index = -1
        best_score = float("-inf")
        for index in remaining:
            redundancy = 0.0
            for selected_index in selected:
                overlap = len(term_sets[index] & term_sets[selected_index])
                union = len(term_sets[index] | term_sets[selected_index])
                redundancy = max(redundancy, overlap / union if union else 0.0)
            score = relevance_weight * relevance[index] - (1.0 - relevance_weight) * redundancy
            if score > best_score:
                best_score = score
                best_index = index
        selected.append(best_index)
        remaining.remove(best_index)
    return [candidates[index] for index in selected]


def _row_metrics(expected: set[str], selected: list[dict[str, Any]]) -> dict[str, float | int]:
    retrieved = [str(row["document_id"]) for row in selected]
    retrieved_set = set(retrieved)
    relevant_ranks = [index for index, document_id in enumerate(retrieved, start=1) if document_id in expected]
    return {
        "document_recall_at_8": len(expected & retrieved_set) / max(1, len(expected)),
        "complete_evidence_recall_at_8": float(expected.issubset(retrieved_set)),
        "hit_at_8": float(bool(expected & retrieved_set)),
        "mrr_at_8": 1.0 / min(relevant_ranks) if relevant_ranks else 0.0,
        "gold_document_chunk_share_at_8": sum(document_id in expected for document_id in retrieved) / max(1, len(retrieved)),
        "unique_documents_at_8": len(retrieved_set),
    }


def _aggregate(rows: list[dict[str, Any]]) -> dict[str, float | int]:
    keys = (
        "document_recall_at_8", "complete_evidence_recall_at_8", "hit_at_8", "mrr_at_8",
        "gold_document_chunk_share_at_8", "unique_documents_at_8",
    )
    return {
        "queries": len(rows),
        **{
            key: round(statistics.mean(float(row[key]) for row in rows), 6) if rows else 0.0
            for key in keys
        },
    }


def _paired_ci(values: list[float]) -> list[float]:
    if not values:
        return [0.0, 0.0]
    rng = np.random.default_rng(SEED)
    samples = rng.choice(np.asarray(values, dtype=np.float64), size=(BOOTSTRAP_SAMPLES, len(values)), replace=True)
    low, high = np.quantile(samples.mean(axis=1), [0.025, 0.975])
    return [round(float(low), 6), round(float(high), 6)]


def _paired_method_comparison(
    per_question: list[dict[str, Any]], reference: str, comparison: str,
) -> dict[str, Any]:
    by_name = {
        name: {row["question_id"]: row for row in per_question if row["configuration"] == name}
        for name in (reference, comparison)
    }
    ids = sorted(set(by_name[reference]) & set(by_name[comparison]))
    metrics = (
        "document_recall_at_8", "complete_evidence_recall_at_8", "gold_document_chunk_share_at_8",
    )
    return {
        "reference": reference,
        "comparison": comparison,
        "paired_queries": len(ids),
        "metrics": {
            metric: {
                "mean_difference": round(statistics.mean(
                    float(by_name[comparison][qid][metric]) - float(by_name[reference][qid][metric])
                    for qid in ids
                ), 6),
                "95pct_bootstrap_ci": _paired_ci([
                    float(by_name[comparison][qid][metric]) - float(by_name[reference][qid][metric])
                    for qid in ids
                ]),
            }
            for metric in metrics
        },
    }


def _evaluate(
    question_path: Path,
    connection: sqlite3.Connection,
    relevance_ratio: float,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    questions = json.loads(question_path.read_text(encoding="utf-8"))
    if not isinstance(questions, list):
        raise ValueError("MultiHop-RAG questions must be a JSON list")
    answerable = [row for row in questions if row.get("evidence_list")]
    nulls = [row for row in questions if not row.get("evidence_list")]
    per_question: list[dict[str, Any]] = []
    route_flags: list[bool] = []
    started = time.perf_counter()

    for index, question in enumerate(answerable, start=1):
        expected = {str(item["title"]) for item in question["evidence_list"] if item.get("title")}
        if len(expected) < 2:
            continue
        candidates = _retrieve(connection, str(question["query"]))
        baseline = candidates[:TOP_K]
        bounded = _select_bounded_source_cap(candidates, TOP_K, per_source_cap=2, rank_window=4)
        diverse = _select_unique_sources(candidates, TOP_K)
        gated = _select_relevance_gated_source_cap(
            candidates,
            TOP_K,
            per_source_cap=2,
            rank_window=4,
            min_relevance_ratio=relevance_ratio,
        )
        mmr_08 = _mmr_select(candidates, TOP_K, relevance_weight=0.8)
        mmr_06 = _mmr_select(candidates, TOP_K, relevance_weight=0.6)
        route = is_multi_source_query(str(question["query"]))
        route_flags.append(route)
        for name, selected in (
            ("global_bm25_top8", baseline),
            ("source_diverse_top8", diverse),
            ("rbsc_cap2_window4", bounded),
            (f"relevance_gated_cap2_window4_ratio_{relevance_ratio:.2f}", gated),
            ("lexical_mmr_lambda_0.8", mmr_08),
            ("lexical_mmr_lambda_0.6", mmr_06),
            ("intent_routed_relevance_gated", gated if route else baseline),
        ):
            per_question.append({
                "configuration": name,
                "question_id": str(question.get("query_id") or f"mh_{index:04d}"),
                "question_type": str(question.get("question_type") or "unknown"),
                "question": str(question["query"]),
                "expected_doc_ids": sorted(expected),
                "retrieved_doc_ids": [str(row["document_id"]) for row in selected],
                **_row_metrics(expected, selected),
            })
        if index % 100 == 0:
            print(f"evaluated answerable MultiHop-RAG queries: {index}/{len(answerable)}", flush=True)

    configurations: dict[str, dict[str, Any]] = {}
    names = sorted({row["configuration"] for row in per_question})
    for name in names:
        rows = [row for row in per_question if row["configuration"] == name]
        configurations[name] = {"overall": _aggregate(rows), "by_question_type": {}}
        for question_type in sorted({row["question_type"] for row in rows}):
            configurations[name]["by_question_type"][question_type] = _aggregate(
                [row for row in rows if row["question_type"] == question_type],
            )

    by_name = {
        name: {row["question_id"]: row for row in per_question if row["configuration"] == name}
        for name in names
    }
    baseline_rows = by_name["global_bm25_top8"]
    paired: dict[str, Any] = {}
    for name in names:
        if name == "global_bm25_top8":
            continue
        ids = sorted(baseline_rows)
        paired[name] = {}
        for metric in (
            "document_recall_at_8", "complete_evidence_recall_at_8", "gold_document_chunk_share_at_8",
        ):
            differences = [float(by_name[name][qid][metric]) - float(baseline_rows[qid][metric]) for qid in ids]
            paired[name][metric] = {
                "mean_difference": round(statistics.mean(differences), 6),
                "95pct_bootstrap_ci": _paired_ci(differences),
            }

    route_metrics = {
        "answerable_multi_evidence_questions": len(route_flags),
        "routed_answerable_questions": sum(route_flags),
        "routing_coverage": round(sum(route_flags) / max(1, len(route_flags)), 6),
    }
    diagnostics = {
        "total_questions": len(questions),
        "answerable_questions": len(answerable),
        "unanswerable_questions": len(nulls),
        "answerable_questions_scored": len(route_flags),
        "questions_skipped_for_fewer_than_two_gold_titles": len(answerable) - len(route_flags),
        "intent_route_coverage_on_answerable_questions": route_metrics,
        "retrieval_seconds": round(time.perf_counter() - started, 3),
        "null_queries_are_reported_but_not_scored_for_abstention": True,
    }
    direct = _paired_method_comparison(
        per_question,
        "intent_routed_relevance_gated",
        "lexical_mmr_lambda_0.6",
    )
    return per_question, {
        "configurations": configurations,
        "paired_differences_vs_global": paired,
        "paired_method_comparisons": {"mmr_0.6_vs_routed_gate": direct},
        "diagnostics": diagnostics,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Cross-dataset source-coverage evaluation on MultiHop-RAG.")
    parser.add_argument("--corpus", type=Path, required=True)
    parser.add_argument("--questions", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--relevance-ratio", type=float, required=True, help="Frozen score gate selected on a separate tuning benchmark.")
    args = parser.parse_args()
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    output_dir = args.output_root / run_id
    output_dir.mkdir(parents=True, exist_ok=False)
    database_path = output_dir / "multihop_bm25_index.sqlite"
    index_started = time.perf_counter()
    index_stats = _build_index(args.corpus, database_path)
    index_stats["build_seconds"] = round(time.perf_counter() - index_started, 3)
    connection = sqlite3.connect(database_path)
    try:
        per_question, evaluation = _evaluate(args.questions, connection, args.relevance_ratio)
    finally:
        connection.close()
    result = {
        "run_id": run_id,
        "benchmark": "MultiHop-RAG dataset (COLM 2024) cross-dataset evaluation",
        "source": "https://github.com/yixuantt/MultiHop-RAG and https://huggingface.co/datasets/yixuantt/MultiHopRAG",
        "license": "ODC-BY",
        "corpus_file_sha256": _sha256(args.corpus),
        "question_file_sha256": _sha256(args.questions),
        "corpus": index_stats,
        "retrieval": {
            "method": "SQLite FTS5 BM25 over InsightEdge-style 1400-character chunks with 280-character overlap",
            "candidate_k": CANDIDATE_K,
            "context_k": TOP_K,
            "score_gate_ratio_frozen_from_enterpriserag_cv": args.relevance_ratio,
        },
        **evaluation,
        "limitations": [
            "This is retrieval-only and does not score generated answers or citation entailment.",
            "The 301 null queries are counted but are not used for an abstention metric in this experiment.",
            "The dataset is smaller and news-domain, so it complements rather than replaces the enterprise corpus result.",
        ],
        "per_question": per_question,
    }
    result_path = output_dir / "results.json"
    result_path.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({
        "output_dir": str(output_dir),
        "corpus": index_stats,
        "diagnostics": evaluation["diagnostics"],
        "configurations": evaluation["configurations"],
        "paired_differences": evaluation["paired_differences_vs_global"],
    }, indent=2))


if __name__ == "__main__":
    main()
