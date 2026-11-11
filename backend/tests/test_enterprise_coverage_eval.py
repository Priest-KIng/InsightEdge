from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path
import zipfile


BACKEND_DIR = Path(__file__).resolve().parents[1]
SCRIPT_DIR = BACKEND_DIR / "scripts"
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from evaluate_enterprise_coverage import (
    _build_index,
    _retrieve,
    _select_bounded_source_cap,
    _select_relevance_gated_source_cap,
    _select_source_cap,
    _select_unique_sources,
    _uses_source_coverage,
)
from evaluate_relevance_gated_coverage import evaluate as evaluate_relevance_gate_cv
from evaluate_multihop_coverage import _paired_method_comparison


def test_source_coverage_selects_one_chunk_per_source_before_repeats() -> None:
    candidates = [
        {"document_id": "doc-a", "chunk_index": 0},
        {"document_id": "doc-a", "chunk_index": 1},
        {"document_id": "doc-b", "chunk_index": 0},
        {"document_id": "doc-c", "chunk_index": 0},
    ]

    selected = _select_unique_sources(candidates, top_k=3)

    assert [(row["document_id"], row["chunk_index"]) for row in selected] == [
        ("doc-a", 0),
        ("doc-b", 0),
        ("doc-c", 0),
    ]


def test_source_coverage_fills_budget_when_corpus_has_fewer_sources() -> None:
    candidates = [
        {"document_id": "doc-a", "chunk_index": 0},
        {"document_id": "doc-a", "chunk_index": 1},
    ]

    selected = _select_unique_sources(candidates, top_k=3)

    assert [(row["document_id"], row["chunk_index"]) for row in selected] == [
        ("doc-a", 0),
        ("doc-a", 1),
    ]


def test_source_cap_preserves_more_evidence_per_source_than_unique_first() -> None:
    candidates = [
        {"document_id": "doc-a", "chunk_index": 0},
        {"document_id": "doc-a", "chunk_index": 1},
        {"document_id": "doc-a", "chunk_index": 2},
        {"document_id": "doc-b", "chunk_index": 0},
        {"document_id": "doc-c", "chunk_index": 0},
    ]

    selected = _select_source_cap(candidates, top_k=4, per_source_cap=2)

    assert [(row["document_id"], row["chunk_index"]) for row in selected] == [
        ("doc-a", 0),
        ("doc-a", 1),
        ("doc-b", 0),
        ("doc-c", 0),
    ]


def test_bounded_source_cap_only_swaps_from_near_top_window():
    candidates = [
        {"document_id": "doc-a", "chunk_index": 0},
        {"document_id": "doc-a", "chunk_index": 1},
        {"document_id": "doc-a", "chunk_index": 2},
        {"document_id": "doc-b", "chunk_index": 0},
        {"document_id": "doc-c", "chunk_index": 0},
        {"document_id": "doc-d", "chunk_index": 0},
    ]

    selected = _select_bounded_source_cap(candidates, top_k=3, per_source_cap=2, rank_window=1)

    assert [(row["document_id"], row["chunk_index"]) for row in selected] == [
        ("doc-a", 0),
        ("doc-a", 1),
        ("doc-b", 0),
    ]


def test_zero_bounded_window_restores_exact_top_k():
    candidates = [
        {"document_id": "doc-a", "chunk_index": 0},
        {"document_id": "doc-a", "chunk_index": 1},
        {"document_id": "doc-a", "chunk_index": 2},
        {"document_id": "doc-b", "chunk_index": 0},
    ]

    selected = _select_bounded_source_cap(candidates, top_k=3, per_source_cap=2, rank_window=0)

    assert selected == candidates[:3]


def test_relevance_gate_admits_competitive_new_source():
    candidates = [
        {"document_id": "doc-a", "chunk_index": 0, "score": -10.0},
        {"document_id": "doc-a", "chunk_index": 1, "score": -9.0},
        {"document_id": "doc-a", "chunk_index": 2, "score": -8.0},
        {"document_id": "doc-b", "chunk_index": 0, "score": -6.0},
        {"document_id": "doc-c", "chunk_index": 0, "score": -1.0},
    ]

    selected = _select_relevance_gated_source_cap(
        candidates,
        top_k=3,
        per_source_cap=2,
        rank_window=2,
        min_relevance_ratio=0.7,
    )

    assert [(row["document_id"], row["chunk_index"]) for row in selected] == [
        ("doc-a", 0),
        ("doc-a", 1),
        ("doc-b", 0),
    ]


def test_relevance_gate_falls_back_to_baseline_for_weak_alternative():
    candidates = [
        {"document_id": "doc-a", "chunk_index": 0, "score": -10.0},
        {"document_id": "doc-a", "chunk_index": 1, "score": -9.0},
        {"document_id": "doc-a", "chunk_index": 2, "score": -8.0},
        {"document_id": "doc-b", "chunk_index": 0, "score": -6.0},
        {"document_id": "doc-c", "chunk_index": 0, "score": -1.0},
    ]

    selected = _select_relevance_gated_source_cap(
        candidates,
        top_k=3,
        per_source_cap=2,
        rank_window=2,
        min_relevance_ratio=0.8,
    )

    assert selected == candidates[:3]


def test_relevance_gate_rejects_invalid_ratio():
    import pytest

    with pytest.raises(ValueError, match="between 0 and 1"):
        _select_relevance_gated_source_cap(
            [{"document_id": "doc-a", "chunk_index": 0, "score": -1.0}],
            top_k=1,
            per_source_cap=2,
            rank_window=4,
            min_relevance_ratio=1.1,
        )


def test_relevance_gate_cv_selects_only_from_training_folds(tmp_path: Path):
    records = []
    for index in range(20):
        expected = [f"gold-{index}", f"gold-extra-{index}"] if index < 10 else [f"gold-{index}"]
        baseline = {
            "question_id": f"q-{index}",
            "expected_doc_ids": expected,
            "document_recall_at_k": 0.5 if index < 10 else 1.0,
            "complete_document_recall_at_k": 0.0 if index < 10 else 1.0,
            "chunk_precision_at_k": 0.8,
        }
        records.append({"configuration": "global_bm25_topk", **baseline})
        records.append({
            "configuration": "intent_routed_source_diverse",
            **baseline,
            "source_coverage_policy": index < 12,
        })
        for ratio, recall, share in (
            (75, 0.8, 0.72),
            (85, 0.7, 0.78),
            (90, 0.65, 0.79),
            (95, 0.6, 0.8),
            (99, 0.55, 0.8),
        ):
            records.append({
                "configuration": f"relevance_gated_cap2_window4_ratio_{ratio:02d}",
                **baseline,
                "document_recall_at_k": recall if index < 10 else 1.0,
                "complete_document_recall_at_k": 0.5 if index < 10 else 1.0,
                "chunk_precision_at_k": share if index < 10 else 0.8,
            })

    result_path = tmp_path / "results.json"
    result_path.write_text(json.dumps({
        "benchmark": "synthetic unit fixture",
        "run_id": "unit",
        "per_question": records,
    }), encoding="utf-8")

    result = evaluate_relevance_gate_cv(result_path)

    assert result["labeled_queries"] == 20
    assert result["multi_gold_queries"] == 10
    primary = result["precision_drop_bound_sensitivity"]["0.025"]
    assert len(primary["folds"]) == 5
    assert sum(primary["oof_selected_ratio_counts"].values()) == 20
    assert "document_recall_at_k" in primary["paired_difference_vs_global_bm25"]


def test_multihop_mmr_comparison_bootstraps_paired_question_differences():
    rows = [
        {"configuration": "intent_routed_relevance_gated", "question_id": "q1",
         "document_recall_at_8": 0.0, "complete_evidence_recall_at_8": 0.0,
         "gold_document_chunk_share_at_8": 0.25},
        {"configuration": "lexical_mmr_lambda_0.6", "question_id": "q1",
         "document_recall_at_8": 0.5, "complete_evidence_recall_at_8": 1.0,
         "gold_document_chunk_share_at_8": 0.5},
        {"configuration": "intent_routed_relevance_gated", "question_id": "q2",
         "document_recall_at_8": 0.5, "complete_evidence_recall_at_8": 0.0,
         "gold_document_chunk_share_at_8": 0.5},
        {"configuration": "lexical_mmr_lambda_0.6", "question_id": "q2",
         "document_recall_at_8": 0.5, "complete_evidence_recall_at_8": 0.0,
         "gold_document_chunk_share_at_8": 0.25},
    ]

    result = _paired_method_comparison(
        rows, "intent_routed_relevance_gated", "lexical_mmr_lambda_0.6",
    )

    assert result["paired_queries"] == 2
    assert result["metrics"]["document_recall_at_8"]["mean_difference"] == 0.25
    assert result["metrics"]["complete_evidence_recall_at_8"]["mean_difference"] == 0.5
    assert result["metrics"]["gold_document_chunk_share_at_8"]["mean_difference"] == 0.0


def test_intent_router_uses_source_coverage_only_for_broad_or_cross_source_queries() -> None:
    assert _uses_source_coverage("Summarize the content across all documents")
    assert _uses_source_coverage("Compare the old and new rollout plans")
    assert not _uses_source_coverage("What is the maximum upload size?")


def test_fts_retrieval_returns_document_ids_and_rank_scores() -> None:
    connection = sqlite3.connect(":memory:")
    connection.execute(
        "CREATE VIRTUAL TABLE chunks USING fts5("
        "document_id UNINDEXED, source_type UNINDEXED, filename UNINDEXED, "
        "chunk_index UNINDEXED, content, tokenize='unicode61 remove_diacritics 2')",
    )
    connection.executemany(
        "INSERT INTO chunks(document_id, source_type, filename, chunk_index, content) VALUES (?, ?, ?, ?, ?)",
        [
            ("doc-a", "docs", "a.txt", 0, "The upload limit is ten megabytes per file."),
            ("doc-b", "docs", "b.txt", 0, "This document describes embedding retrieval."),
        ],
    )

    rows = _retrieve(connection, "What is the upload limit per file?", candidate_k=5)

    assert rows
    assert rows[0]["document_id"] == "doc-a"
    assert rows[0]["filename"] == "a.txt"
    assert isinstance(rows[0]["score"], float)


def test_archive_indexing_reads_zip_members_without_extracting(tmp_path: Path) -> None:
    archive_path = tmp_path / "all_documents.zip"
    database_path = tmp_path / "index.sqlite"
    with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(
            "docs/dsid_a__upload-policy.txt",
            "The upload limit is ten megabytes per file.",
        )
        archive.writestr(
            "mail/dsid_b__embedding-plan.txt",
            "This note describes embedding retrieval and vector search.",
        )

    manifest = _build_index(tmp_path, database_path, archive_path=archive_path)

    assert manifest["document_count"] == 2
    assert manifest["chunk_count"] >= 2
    assert manifest["source_files"] == ["docs", "mail"]
    connection = sqlite3.connect(database_path)
    try:
        rows = _retrieve(connection, "upload limit", candidate_k=5)
    finally:
        connection.close()
    assert rows[0]["document_id"] == "dsid_a"
