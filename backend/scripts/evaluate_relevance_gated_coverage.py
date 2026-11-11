from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any

import numpy as np

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from evaluate_query_routing import _stratified_folds

SEED = 20261111
FOLDS = 5
BOOTSTRAP_SAMPLES = 5000
RATIOS = (75, 85, 90, 95, 99)
PRECISION_DROP_BOUNDS = (0.01, 0.025, 0.05)
BASELINE = "global_bm25_topk"
ROUTER = "intent_routed_source_diverse"


def _mean(rows: list[dict[str, Any]], key: str) -> float:
    return float(np.mean([float(row[key]) for row in rows])) if rows else 0.0


def _metrics(rows: list[dict[str, Any]]) -> dict[str, float | int]:
    multi = [row for row in rows if len(row["expected_doc_ids"]) > 1]
    return {
        "queries": len(rows),
        "document_recall_at_k": round(_mean(rows, "document_recall_at_k"), 6),
        "complete_document_recall_at_k": round(_mean(rows, "complete_document_recall_at_k"), 6),
        "gold_document_chunk_share_at_k": round(_mean(rows, "chunk_precision_at_k"), 6),
        "multi_gold_queries": len(multi),
        "multi_gold_document_recall_at_k": round(_mean(multi, "document_recall_at_k"), 6),
        "multi_gold_complete_document_recall_at_k": round(_mean(multi, "complete_document_recall_at_k"), 6),
        "multi_gold_chunk_share_at_k": round(_mean(multi, "chunk_precision_at_k"), 6),
    }


def _paired_bootstrap(
    values: list[float], seed: int = SEED, samples: int = BOOTSTRAP_SAMPLES,
) -> list[float]:
    if not values:
        return [0.0, 0.0]
    array = np.asarray(values, dtype=np.float64)
    rng = np.random.default_rng(seed)
    draws = rng.choice(array, size=(samples, len(array)), replace=True).mean(axis=1)
    low, high = np.quantile(draws, [0.025, 0.975])
    return [round(float(low), 6), round(float(high), 6)]


def evaluate(results_path: Path) -> dict[str, Any]:
    payload = json.loads(results_path.read_text(encoding="utf-8"))
    configurations: dict[str, dict[str, dict[str, Any]]] = {}
    for row in payload["per_question"]:
        configurations.setdefault(str(row["configuration"]), {})[str(row["question_id"])] = row

    baseline = configurations[BASELINE]
    router_rows = configurations[ROUTER]
    question_ids = sorted(baseline)
    labels = [len(set(baseline[qid]["expected_doc_ids"])) > 1 for qid in question_ids]
    folds = _stratified_folds(labels, FOLDS, SEED)
    query_index = {qid: index for index, qid in enumerate(question_ids)}
    routed = {qid for qid, row in router_rows.items() if bool(row["source_coverage_policy"])}

    gate_rows = {
        ratio: configurations[f"relevance_gated_cap2_window4_ratio_{ratio:02d}"]
        for ratio in RATIOS
    }

    output: dict[str, Any] = {
        "benchmark": payload["benchmark"],
        "run_id": payload["run_id"],
        "labeled_queries": len(question_ids),
        "multi_gold_queries": sum(labels),
        "router_flagged_queries": len(routed),
        "method": {
            "folds": FOLDS,
            "seed": SEED,
            "ratios": [ratio / 100 for ratio in RATIOS],
            "training_objective": (
                "For each outer fold, maximize document recall on training queries subject to "
                "gold-document chunk share staying within the stated absolute drop from global BM25; "
                "ties prefer higher chunk share, then the stricter gate."
            ),
            "deployment_route": "The fixed InsightEdge multi-source intent rule selects which queries receive the gate.",
            "score_gate": "Admit an outside-top-k source candidate only if its FTS5 BM25 magnitude is at least ratio times the original kth candidate's magnitude.",
            "bootstrap_samples": BOOTSTRAP_SAMPLES,
        },
        "global_bm25_oof_reference": _metrics([baseline[qid] for qid in question_ids]),
        "precision_drop_bound_sensitivity": {},
        "limitations": [
            "The held-out folds are query-level splits from one synthetic enterprise benchmark; they are not an independent corpus or domain replication.",
            "The source-coverage intent route is fixed during this evaluation but was previously inspected on this benchmark.",
            "Gold labels identify supporting documents, not relevant passages; gold-document chunk share is a proxy, not citation entailment.",
            "This isolates BM25 retrieval and evidence selection; it does not establish end-to-end hybrid RAG answer quality.",
        ],
    }

    for max_drop in PRECISION_DROP_BOUNDS:
        oof_choice: dict[str, int | None] = {}
        oof_fold: dict[str, int] = {}
        fold_reports: list[dict[str, Any]] = []
        for fold_number, test_indices in enumerate(folds, start=1):
            test_set = set(test_indices)
            train_indices = [idx for idx in range(len(question_ids)) if idx not in test_set]
            train_ids = [question_ids[idx] for idx in train_indices]
            test_ids = [question_ids[idx] for idx in test_indices]
            baseline_train_metrics = _metrics([baseline[qid] for qid in train_ids])

            candidates: list[tuple[tuple[float, float, int], int | None, list[dict[str, Any]]]] = []
            baseline_rows = [baseline[qid] for qid in train_ids]
            candidates.append((
                (
                    float(baseline_train_metrics["document_recall_at_k"]),
                    float(baseline_train_metrics["gold_document_chunk_share_at_k"]),
                    100,
                ),
                None,
                baseline_rows,
            ))
            for ratio in RATIOS:
                rows = [
                    gate_rows[ratio][qid] if qid in routed else baseline[qid]
                    for qid in train_ids
                ]
                metrics = _metrics(rows)
                if float(metrics["gold_document_chunk_share_at_k"]) < (
                    float(baseline_train_metrics["gold_document_chunk_share_at_k"]) - max_drop
                ):
                    continue
                candidates.append((
                    (
                        float(metrics["document_recall_at_k"]),
                        float(metrics["gold_document_chunk_share_at_k"]),
                        ratio,
                    ),
                    ratio,
                    rows,
                ))
            _, chosen_ratio, chosen_train_rows = max(candidates, key=lambda item: item[0])
            heldout_rows = [
                gate_rows[chosen_ratio][qid] if chosen_ratio is not None and qid in routed else baseline[qid]
                for qid in test_ids
            ]
            for qid, row in zip(test_ids, heldout_rows):
                oof_choice[qid] = chosen_ratio
                oof_fold[qid] = fold_number
            fold_reports.append({
                "fold": fold_number,
                "train_queries": len(train_ids),
                "test_queries": len(test_ids),
                "chosen_ratio": None if chosen_ratio is None else chosen_ratio / 100,
                "training_metrics": _metrics(chosen_train_rows),
                "heldout_metrics": _metrics(heldout_rows),
            })

        oof_rows = [
            gate_rows[oof_choice[qid]][qid]
            if oof_choice[qid] is not None and qid in routed
            else baseline[qid]
            for qid in question_ids
        ]
        base_rows = [baseline[qid] for qid in question_ids]
        differences = {
            metric: [float(new[metric]) - float(old[metric]) for new, old in zip(oof_rows, base_rows)]
            for metric in ("document_recall_at_k", "complete_document_recall_at_k", "chunk_precision_at_k")
        }
        multi_differences = {
            metric: [
                float(new[metric]) - float(old[metric])
                for new, old, is_multi in zip(oof_rows, base_rows, labels)
                if is_multi
            ]
            for metric in ("document_recall_at_k", "complete_document_recall_at_k", "chunk_precision_at_k")
        }
        query_level_oof = []
        for qid, selected, base, is_multi in zip(question_ids, oof_rows, base_rows, labels):
            query_level_oof.append({
                "question_id": qid,
                "fold": oof_fold[qid],
                "selected_ratio": None if oof_choice[qid] is None else oof_choice[qid] / 100,
                "routed": qid in routed,
                "multi_gold": is_multi,
                "baseline": {
                    metric: float(base[metric])
                    for metric in ("document_recall_at_k", "complete_document_recall_at_k", "chunk_precision_at_k")
                },
                "selected": {
                    metric: float(selected[metric])
                    for metric in ("document_recall_at_k", "complete_document_recall_at_k", "chunk_precision_at_k")
                },
            })
        output["precision_drop_bound_sensitivity"][str(max_drop)] = {
            "out_of_fold_metrics": _metrics(oof_rows),
            "paired_difference_vs_global_bm25": {
                metric: {
                    "mean": round(float(np.mean(values)), 6),
                    "95pct_bootstrap_ci": _paired_bootstrap(values, seed=SEED + int(max_drop * 1000)),
                }
                for metric, values in differences.items()
            },
            "multi_gold_paired_difference_vs_global_bm25": {
                metric: {
                    "mean": round(float(np.mean(values)), 6),
                    "95pct_bootstrap_ci": _paired_bootstrap(values, seed=SEED + int(max_drop * 1000) + 1),
                }
                for metric, values in multi_differences.items()
            },
            "folds": fold_reports,
            "out_of_fold_query_metrics": query_level_oof,
            "oof_selected_ratio_counts": {
                str(ratio / 100 if ratio is not None else "baseline"): sum(value == ratio for value in oof_choice.values())
                for ratio in [None, *RATIOS]
            },
        }
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description="Cross-validated evaluation of relevance-gated source coverage.")
    parser.add_argument("--results", type=Path, required=True, help="Full evaluator results.json with ratio sweep configurations.")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = evaluate(args.results)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2), encoding="utf-8")
    primary = result["precision_drop_bound_sensitivity"]["0.025"]
    print(json.dumps({
        "queries": result["labeled_queries"],
        "multi_gold": result["multi_gold_queries"],
        "precision_drop_bound": 0.025,
        "oof": primary["out_of_fold_metrics"],
        "multi_gold_delta": primary["multi_gold_paired_difference_vs_global_bm25"]["document_recall_at_k"],
    }, indent=2))


if __name__ == "__main__":
    main()
