from __future__ import annotations

import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
SCRIPT_DIR = BACKEND_DIR / "scripts"
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from evaluate_query_routing import _counts, _stratified_folds


def test_stratified_routing_folds_are_deterministic_and_cover_all_queries() -> None:
    labels = [True, False, False, True, False, False, False, False, True, False]

    folds = _stratified_folds(labels, folds=5, seed=20261111)

    assert folds == _stratified_folds(labels, folds=5, seed=20261111)
    assert sorted(index for fold in folds for index in fold) == list(range(len(labels)))
    assert all(fold for fold in folds)


def test_routing_metrics_count_false_positives_and_false_negatives() -> None:
    result = _counts([True, True, False, False], [True, False, True, False])

    assert result["true_positive"] == 1
    assert result["false_positive"] == 1
    assert result["false_negative"] == 1
    assert result["precision"] == 0.5
    assert result["recall"] == 0.5
    assert result["f1"] == 0.5
