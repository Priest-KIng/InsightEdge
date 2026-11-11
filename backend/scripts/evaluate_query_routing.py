from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import random
import sys
from typing import Any

import numpy as np

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.services.router import has_compound_interrogative_clause, is_multi_source_query_explicit

THRESHOLDS = (15, 20, 25, 30, 35, 40, 45)
FOLDS = 5
SEED = 20261111
BOOTSTRAP_SAMPLES = 5000


def _counts(labels: list[bool], predictions: list[bool]) -> dict[str, float | int]:
    true_positive = sum(label and prediction for label, prediction in zip(labels, predictions))
    false_positive = sum(not label and prediction for label, prediction in zip(labels, predictions))
    false_negative = sum(label and not prediction for label, prediction in zip(labels, predictions))
    precision = true_positive / max(1, true_positive + false_positive)
    recall = true_positive / max(1, true_positive + false_negative)
    f1 = 2 * precision * recall / max(1e-12, precision + recall)
    return {
        "queries": len(labels),
        "true_positive": true_positive,
        "false_positive": false_positive,
        "false_negative": false_negative,
        "precision": round(precision, 6),
        "recall": round(recall, 6),
        "f1": round(f1, 6),
    }


def _stratified_folds(labels: list[bool], folds: int, seed: int) -> list[list[int]]:
    rng = random.Random(seed)
    assignments: list[list[int]] = [[] for _ in range(folds)]
    for target in (False, True):
        indices = [index for index, label in enumerate(labels) if label is target]
        rng.shuffle(indices)
        for position, index in enumerate(indices):
            assignments[position % folds].append(index)
    return [sorted(fold) for fold in assignments]


def _bootstrap_intervals(
    labels: list[bool], predictions: list[bool], seed: int = SEED,
) -> dict[str, list[float]]:
    label_array = np.asarray(labels, dtype=np.int8)
    prediction_array = np.asarray(predictions, dtype=np.int8)
    rng = np.random.default_rng(seed)
    draws = rng.integers(0, len(labels), size=(BOOTSTRAP_SAMPLES, len(labels)))
    sampled_labels = label_array[draws]
    sampled_predictions = prediction_array[draws]
    true_positive = np.sum(sampled_labels * sampled_predictions, axis=1)
    false_positive = np.sum((1 - sampled_labels) * sampled_predictions, axis=1)
    false_negative = np.sum(sampled_labels * (1 - sampled_predictions), axis=1)
    precision = true_positive / np.maximum(1, true_positive + false_positive)
    recall = true_positive / np.maximum(1, true_positive + false_negative)
    f1 = 2 * precision * recall / np.maximum(1e-12, precision + recall)
    return {
        metric: [round(float(value), 6) for value in np.quantile(samples, [0.025, 0.975])]
        for metric, samples in (("precision", precision), ("recall", recall), ("f1", f1))
    }


def evaluate_questions(question_path: Path) -> dict[str, Any]:
    questions = [
        json.loads(line)
        for line in question_path.read_text(encoding="utf-8-sig").splitlines()
        if line.strip()
    ]
    questions = [row for row in questions if row.get("expected_doc_ids")]
    labels = [len(set(map(str, row["expected_doc_ids"]))) > 1 for row in questions]
    folds = _stratified_folds(labels, FOLDS, SEED)

    explicit_predictions = [is_multi_source_query_explicit(str(row["question"])) for row in questions]
    out_of_fold_predictions = [False] * len(questions)
    fold_reports: list[dict[str, Any]] = []
    for fold_number, test_indices in enumerate(folds, start=1):
        test_set = set(test_indices)
        train_indices = [index for index in range(len(questions)) if index not in test_set]
        best_threshold: int | None = None
        best_key: tuple[float, float, int] | None = None
        for threshold in THRESHOLDS:
            train_predictions = [
                explicit_predictions[index]
                or has_compound_interrogative_clause(str(questions[index]["question"]), threshold)
                for index in train_indices
            ]
            train_counts = _counts([labels[index] for index in train_indices], train_predictions)
            # Prefer F1, then precision, then the larger threshold to limit extra routing.
            candidate_key = (float(train_counts["f1"]), float(train_counts["precision"]), threshold)
            if best_key is None or candidate_key > best_key:
                best_key = candidate_key
                best_threshold = threshold

        assert best_threshold is not None
        test_predictions = [
            explicit_predictions[index]
            or has_compound_interrogative_clause(str(questions[index]["question"]), best_threshold)
            for index in test_indices
        ]
        for index, prediction in zip(test_indices, test_predictions):
            out_of_fold_predictions[index] = prediction
        fold_reports.append({
            "fold": fold_number,
            "train_queries": len(train_indices),
            "test_queries": len(test_indices),
            "selected_minimum_words": best_threshold,
            "training_metrics": _counts([labels[index] for index in train_indices], [
                explicit_predictions[index]
                or has_compound_interrogative_clause(str(questions[index]["question"]), best_threshold)
                for index in train_indices
            ]),
            "heldout_metrics": _counts([labels[index] for index in test_indices], test_predictions),
        })

    baseline_metrics = _counts(labels, explicit_predictions)
    oof_metrics = _counts(labels, out_of_fold_predictions)
    return {
        "benchmark": "EnterpriseRAG-Bench v1.0.0",
        "question_file": question_path.name,
        "question_file_sha256": hashlib.sha256(question_path.read_bytes()).hexdigest(),
        "labeled_questions": len(questions),
        "multi_gold_questions": sum(labels),
        "target_definition": "More than one distinct expected_doc_id; a document-count proxy, not a human query-intent annotation.",
        "method": {
            "folds": FOLDS,
            "seed": SEED,
            "threshold_candidates_minimum_words": list(THRESHOLDS),
            "training_objective": "Maximize F1, then precision, then choose the larger word threshold.",
            "selection": "Threshold chosen on each training fold; metrics aggregated from out-of-fold predictions.",
            "bootstrap_samples": BOOTSTRAP_SAMPLES,
            "bootstrap_seed": SEED,
        },
        "explicit_intent_baseline": {
            **baseline_metrics,
            "bootstrap_95pct_ci": _bootstrap_intervals(labels, explicit_predictions),
        },
        "cross_validated_compound_clause_router": {
            **oof_metrics,
            "bootstrap_95pct_ci": _bootstrap_intervals(labels, out_of_fold_predictions),
        },
        "folds_detail": fold_reports,
        "limitations": [
            "Expected document-ID multiplicity is a noisy proxy for whether a user intends a cross-document answer.",
            "This evaluates routing decisions only; it does not measure retrieval quality or answer correctness.",
            "The compound-clause feature family was motivated by inspection of this benchmark; use an independent benchmark and human intent labels for confirmation.",
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Cross-validate InsightEdge multi-source query routing.")
    parser.add_argument("--questions", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    result = evaluate_questions(args.questions)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps({
        "baseline": result["explicit_intent_baseline"],
        "cross_validated": result["cross_validated_compound_clause_router"],
        "thresholds": [fold["selected_minimum_words"] for fold in result["folds_detail"]],
    }, indent=2))


if __name__ == "__main__":
    main()
