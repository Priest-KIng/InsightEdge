from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
from pathlib import PurePosixPath
import re
import sqlite3
import statistics
import sys
import time
from typing import Any
import zipfile

import numpy as np

BACKEND_DIR = Path(__file__).resolve().parents[1]
PROJECT_DIR = BACKEND_DIR.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.services.chunker import chunk_text
from app.services.router import is_multi_source_query


STOPWORDS = {
    "a", "an", "and", "are", "as", "at", "be", "by", "can", "does", "for", "from",
    "how", "in", "is", "it", "of", "on", "or", "the", "to", "what", "which", "who",
    "why", "with", "would", "could", "should", "did", "do", "was", "were", "when", "where",
}
MULTI_SOURCE_TYPES = {"completeness", "conflicting_info", "high_level"}
INSERT_BATCH_CHUNKS = 10_000


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _document_id(path: Path) -> str:
    return path.name.split("__", 1)[0]


def _query_terms(question: str) -> list[str]:
    return [
        term for term in re.findall(r"[a-zA-Z0-9_]+", question.casefold())
        if term not in STOPWORDS and len(term) > 1
    ]


def _uses_source_coverage(question: str) -> bool:
    """Use the same intent router as the serving path."""
    return is_multi_source_query(question)


def _chunks_for_file(path: Path) -> list[str]:
    text = path.read_text(encoding="utf-8", errors="replace")
    return chunk_text(text, chunk_size=1400, chunk_overlap=280)


def _build_index(
    corpus_root: Path,
    database_path: Path,
    source_limit: int | None = None,
    archive_path: Path | None = None,
) -> dict[str, Any]:
    archive = zipfile.ZipFile(archive_path) if archive_path is not None else None
    try:
        files = sorted(corpus_root.glob("*_slice_*/**/*.txt")) if archive is None else []
        if archive is not None:
            archive_entries: list[tuple[Any, str, str]] = []
            seen_targets: set[str] = set()
            for entry in archive.infolist():
                if not entry.filename.casefold().endswith(".txt"):
                    continue
                parts = PurePosixPath(entry.filename).parts
                if len(parts) < 2 or parts[0] in {"", ".", ".."}:
                    raise ValueError(f"Unexpected benchmark archive path: {entry.filename!r}")
                source_type = parts[0]
                filename = parts[-1]
                target_key = f"{source_type}/{filename}".casefold()
                if target_key in seen_targets:
                    source = PurePosixPath(filename)
                    suffix = hashlib.sha256(entry.filename.encode("utf-8")).hexdigest()[:10]
                    filename = f"{source.stem}__archive_{suffix}{source.suffix}"
                    target_key = f"{source_type}/{filename}".casefold()
                if target_key in seen_targets:
                    raise ValueError(f"Flattened archive path collision: {entry.filename!r}")
                seen_targets.add(target_key)
                archive_entries.append((entry, source_type, filename))
            archive_entries.sort(key=lambda item: (item[1], item[2]))
            entries: list[Any] = archive_entries
        else:
            entries = files
        if source_limit is not None:
            entries = entries[:source_limit]
        if not entries:
            raise ValueError("No EnterpriseRAG-Bench .txt files found in the selected corpus")

        database_path.parent.mkdir(parents=True, exist_ok=True)
        if database_path.exists():
            database_path.unlink()
        connection = sqlite3.connect(database_path)
        try:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute("PRAGMA synchronous=NORMAL")
            connection.execute("PRAGMA temp_store=MEMORY")
            connection.execute("PRAGMA cache_size=-65536")
            connection.execute(
                "CREATE VIRTUAL TABLE chunks USING fts5("
                "document_id UNINDEXED, source_type UNINDEXED, filename UNINDEXED, "
                "chunk_index UNINDEXED, content, tokenize='unicode61 remove_diacritics 2')",
            )
            rows: list[tuple[str, str, str, int, str]] = []
            total_bytes = 0
            total_chunks = 0
            manifest = hashlib.sha256()
            seen_document_ids: set[str] = set()
            duplicate_document_id_instances = 0

            for file_number, entry in enumerate(entries, start=1):
                if archive is not None:
                    archive_entry, source_type, filename = entry
                    size_bytes = archive_entry.file_size
                    text = archive.read(archive_entry).decode("utf-8", errors="replace")
                else:
                    filename = entry.name
                    source_type = entry.parent.name
                    size_bytes = entry.stat().st_size
                    text = entry.read_text(encoding="utf-8", errors="replace")

                total_bytes += size_bytes
                document_id = filename.split("__", 1)[0]
                if document_id in seen_document_ids:
                    duplicate_document_id_instances += 1
                seen_document_ids.add(document_id)
                chunks = chunk_text(text, chunk_size=1400, chunk_overlap=280)
                rows.extend(
                    (document_id, source_type, filename, index, chunk)
                    for index, chunk in enumerate(chunks)
                )
                manifest.update(document_id.encode("utf-8"))
                manifest.update(b"\0")
                manifest.update(filename.encode("utf-8"))
                manifest.update(b"\n")
                if len(rows) >= INSERT_BATCH_CHUNKS:
                    connection.executemany(
                        "INSERT INTO chunks(document_id, source_type, filename, chunk_index, content) "
                        "VALUES (?, ?, ?, ?, ?)",
                        rows,
                    )
                    connection.commit()
                    total_chunks += len(rows)
                    rows.clear()
                if file_number % 5000 == 0:
                    print(f"indexed source files: {file_number}/{len(entries)}", flush=True)
            if rows:
                connection.executemany(
                    "INSERT INTO chunks(document_id, source_type, filename, chunk_index, content) "
                    "VALUES (?, ?, ?, ?, ?)",
                    rows,
                )
                total_chunks += len(rows)
                connection.commit()
            connection.execute("INSERT INTO chunks(chunks) VALUES ('optimize')")
            connection.commit()
            return {
                "document_count": len(entries),
                "document_bytes": total_bytes,
                "chunk_count": total_chunks,
                "insert_batch_chunks": INSERT_BATCH_CHUNKS,
                "document_manifest_sha256": manifest.hexdigest(),
                "unique_document_id_count": len(seen_document_ids),
                "duplicate_document_id_instances": duplicate_document_id_instances,
                "source_files": sorted(
                    {
                        entry[1] if archive is not None else entry.parent.name
                        for entry in entries
                    },
                ),
            }
        finally:
            connection.close()
    finally:
        if archive is not None:
            archive.close()


def _manifest_hash(files: list[Path]) -> str:
    digest = hashlib.sha256()
    for path in files:
        digest.update(_document_id(path).encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.name.encode("utf-8"))
        digest.update(b"\n")
    return digest.hexdigest()


def _describe_index(corpus_root: Path, database_path: Path, source_limit: int | None = None) -> dict[str, Any]:
    files = sorted(corpus_root.glob("*_slice_*/**/*.txt"))
    if source_limit is not None:
        files = files[:source_limit]
    connection = sqlite3.connect(database_path)
    try:
        chunk_count = int(connection.execute("SELECT COUNT(*) FROM chunks").fetchone()[0])
    finally:
        connection.close()
    return {
        "document_count": len(files),
        "document_bytes": sum(path.stat().st_size for path in files),
        "chunk_count": chunk_count,
        "document_manifest_sha256": _manifest_hash(files),
        "source_files": sorted({path.parent.name for path in files}),
    }


def _retrieve(connection: sqlite3.Connection, question: str, candidate_k: int) -> list[dict[str, Any]]:
    terms = list(dict.fromkeys(_query_terms(question)))
    if not terms:
        return []
    match = " OR ".join(f'"{term.replace(chr(34), "")}"' for term in terms)
    rows = connection.execute(
        "SELECT document_id, source_type, filename, chunk_index, content, bm25(chunks) AS score "
        "FROM chunks WHERE chunks MATCH ? ORDER BY score LIMIT ?",
        (match, candidate_k),
    ).fetchall()
    return [
        {
            "document_id": row[0], "source_type": row[1], "filename": row[2],
            "chunk_index": row[3], "content": row[4], "score": float(row[5]),
        }
        for row in rows
    ]


def _select_unique_sources(candidates: list[dict[str, Any]], top_k: int) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    seen_documents: set[str] = set()
    for row in candidates:
        document_id = str(row["document_id"])
        if document_id in seen_documents:
            continue
        selected.append(row)
        seen_documents.add(document_id)
        if len(selected) >= top_k:
            return selected
    selected_ids = {(row["document_id"], row["chunk_index"]) for row in selected}
    for row in candidates:
        key = (row["document_id"], row["chunk_index"])
        if key in selected_ids:
            continue
        selected.append(row)
        selected_ids.add(key)
        if len(selected) >= top_k:
            break
    return selected


def _select_source_cap(
    candidates: list[dict[str, Any]],
    top_k: int,
    per_source_cap: int,
) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    counts: Counter[str] = Counter()
    selected_keys: set[tuple[str, int]] = set()
    for row in candidates:
        source = str(row["document_id"])
        if counts[source] >= per_source_cap:
            continue
        selected.append(row)
        counts[source] += 1
        selected_keys.add((source, int(row["chunk_index"])))
        if len(selected) >= top_k:
            return selected
    for row in candidates:
        key = (str(row["document_id"]), int(row["chunk_index"]))
        if key in selected_keys:
            continue
        selected.append(row)
        selected_keys.add(key)
        if len(selected) >= top_k:
            break
    return selected


def _select_bounded_source_cap(
    candidates: list[dict[str, Any]],
    top_k: int,
    per_source_cap: int,
    rank_window: int,
) -> list[dict[str, Any]]:
    """Cap source repetition inside a bounded rank window; retain top-k fallback."""
    selected: list[dict[str, Any]] = []
    counts: Counter[str] = Counter()
    selected_keys: set[tuple[str, int]] = set()
    near_top = candidates[: top_k + max(0, rank_window)]
    for row in near_top:
        source = str(row["document_id"])
        if counts[source] >= per_source_cap:
            continue
        selected.append(row)
        counts[source] += 1
        selected_keys.add((source, int(row["chunk_index"])))
        if len(selected) >= top_k:
            return selected
    for row in candidates[:top_k]:
        key = (str(row["document_id"]), int(row["chunk_index"]))
        if key in selected_keys:
            continue
        selected.append(row)
        selected_keys.add(key)
        if len(selected) >= top_k:
            break
    rank_by_key = {
        (str(row["document_id"]), int(row["chunk_index"])): rank
        for rank, row in enumerate(candidates)
    }
    return sorted(
        selected,
        key=lambda row: rank_by_key[(str(row["document_id"]), int(row["chunk_index"]))],
    )


def _evaluate_ranked(
    questions: list[dict[str, Any]],
    connection: sqlite3.Connection,
    top_k: int,
    candidate_k: int,
) -> tuple[list[dict[str, Any]], int]:
    records: list[dict[str, Any]] = []
    fully_supported = 0
    for question in questions:
        expected = {str(value) for value in question.get("expected_doc_ids", [])}
        if not expected:
            continue
        candidates = _retrieve(connection, str(question["question"]), candidate_k)
        fully_supported += 1
        baseline = candidates[:top_k]
        diverse = _select_unique_sources(candidates, top_k)
        cap2 = _select_source_cap(candidates, top_k, per_source_cap=2)
        cap3 = _select_source_cap(candidates, top_k, per_source_cap=3)
        bounded = {
            f"bounded_cap2_window_{window}": _select_bounded_source_cap(
                candidates, top_k, per_source_cap=2, rank_window=window,
            )
            for window in (0, 4, 8, 12, 16, 32, 64)
        }
        heuristic = diverse if _uses_source_coverage(str(question["question"])) else baseline
        heuristic_cap2 = cap2 if _uses_source_coverage(str(question["question"])) else baseline
        oracle = diverse if len(expected) > 1 or str(question.get("question_type")) in MULTI_SOURCE_TYPES else baseline
        for name, selected in (
            ("global_bm25_topk", baseline),
            ("source_diverse_topk", diverse),
            ("source_cap_2", cap2),
            ("source_cap_3", cap3),
            *bounded.items(),
            ("intent_routed_source_diverse", heuristic),
            ("intent_routed_source_cap_2", heuristic_cap2),
            ("oracle_intent_upper_bound", oracle),
        ):
            retrieved_ids = [str(row["document_id"]) for row in selected]
            relevant = [doc_id for doc_id in retrieved_ids if doc_id in expected]
            first_rank = next((idx for idx, doc_id in enumerate(retrieved_ids, 1) if doc_id in expected), None)
            records.append(
                {
                    "configuration": name,
                    "question_id": str(question.get("question_id", "")),
                    "question_type": str(question.get("question_type", "")),
                    "question": str(question["question"]),
                    "expected_doc_ids": sorted(expected),
                    "retrieved_doc_ids": retrieved_ids,
                    "retrieved_chunk_ids": [
                        f"{row['document_id']}:{row['chunk_index']}" for row in selected
                    ],
                    "document_recall_at_k": len(set(relevant) & expected) / len(expected),
                    "complete_document_recall_at_k": float(expected.issubset(set(retrieved_ids))),
                    "hit_at_k": float(bool(relevant)),
                    "mrr_at_k": 1.0 / first_rank if first_rank else 0.0,
                    "chunk_precision_at_k": len(relevant) / max(1, len(selected)),
                    "unique_sources_at_k": len(set(retrieved_ids)),
                    "source_coverage_policy": (
                        name in {"source_diverse_topk", "source_cap_2", "source_cap_3"}
                        or name.startswith("bounded_cap2_window_")
                        or (name.startswith("intent_routed_source_") and _uses_source_coverage(str(question["question"])))
                        or (name == "oracle_intent_upper_bound" and (len(expected) > 1 or str(question.get("question_type")) in MULTI_SOURCE_TYPES))
                    ),
                    "candidate_top10": [
                        {"document_id": row["document_id"], "chunk_index": row["chunk_index"], "filename": row["filename"], "score": row["score"]}
                        for row in candidates[:10]
                    ],
                },
            )
    return records, fully_supported


def _document_rows(connection: sqlite3.Connection) -> set[str]:
    return {str(row[0]) for row in connection.execute("SELECT DISTINCT document_id FROM chunks")}


def _aggregate(records: list[dict[str, Any]]) -> dict[str, Any]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        groups[record["configuration"]].append(record)
    output: dict[str, Any] = {}
    for name, rows in groups.items():
        metrics = (
            "document_recall_at_k", "complete_document_recall_at_k", "hit_at_k", "mrr_at_k",
            "chunk_precision_at_k", "unique_sources_at_k",
        )
        output[name] = {
            "queries": len(rows),
            **{metric: round(statistics.mean(float(row[metric]) for row in rows), 6) for metric in metrics},
        }
        by_type: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in rows:
            by_type[row["question_type"]].append(row)
        output[name]["by_question_type"] = {
            query_type: {
                "queries": len(type_rows),
                "document_recall_at_k": round(statistics.mean(float(row["document_recall_at_k"]) for row in type_rows), 6),
                "complete_document_recall_at_k": round(statistics.mean(float(row["complete_document_recall_at_k"]) for row in type_rows), 6),
                "chunk_precision_at_k": round(statistics.mean(float(row["chunk_precision_at_k"]) for row in type_rows), 6),
            }
            for query_type, type_rows in sorted(by_type.items())
        }
        by_scope: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in rows:
            scope = "multi_gold_source" if len(row["expected_doc_ids"]) > 1 else "single_gold_source"
            by_scope[scope].append(row)
        output[name]["by_gold_source_count"] = {
            scope: {
                "queries": len(scope_rows),
                "document_recall_at_k": round(statistics.mean(float(row["document_recall_at_k"]) for row in scope_rows), 6),
                "complete_document_recall_at_k": round(statistics.mean(float(row["complete_document_recall_at_k"]) for row in scope_rows), 6),
                "chunk_precision_at_k": round(statistics.mean(float(row["chunk_precision_at_k"]) for row in scope_rows), 6),
            }
            for scope, scope_rows in sorted(by_scope.items())
        }
    return output


def _bootstrap_ci(values: list[float], seed: int = 20261111, samples: int = 5000) -> list[float]:
    if not values:
        return [0.0, 0.0]
    rng = np.random.default_rng(seed)
    draws = rng.choice(np.asarray(values, dtype=np.float64), size=(samples, len(values)), replace=True)
    lower, upper = np.quantile(draws.mean(axis=1), [0.025, 0.975])
    return [round(float(lower), 6), round(float(upper), 6)]


def _paired_intervals(records: list[dict[str, Any]], baseline_name: str) -> dict[str, Any]:
    by_configuration = {
        name: {row["question_id"]: row for row in records if row["configuration"] == name}
        for name in {row["configuration"] for row in records}
    }
    baseline = by_configuration[baseline_name]
    output: dict[str, Any] = {}
    for name, query_rows in by_configuration.items():
        if name == baseline_name:
            continue
        shared_ids = sorted(set(baseline) & set(query_rows))
        output[name] = {"paired_queries": len(shared_ids)}
        for metric in ("document_recall_at_k", "complete_document_recall_at_k", "chunk_precision_at_k"):
            differences = [float(query_rows[qid][metric]) - float(baseline[qid][metric]) for qid in shared_ids]
            output[name][metric + "_difference"] = round(statistics.mean(differences), 6) if differences else 0.0
            output[name][metric + "_difference_95pct_bootstrap_ci"] = _bootstrap_ci(differences)
            multi_differences = [
                float(query_rows[qid][metric]) - float(baseline[qid][metric])
                for qid in shared_ids
                if len(baseline[qid]["expected_doc_ids"]) > 1
            ]
            output[name]["multi_gold_" + metric + "_difference"] = (
                round(statistics.mean(multi_differences), 6) if multi_differences else 0.0
            )
            output[name]["multi_gold_" + metric + "_difference_95pct_bootstrap_ci"] = _bootstrap_ci(multi_differences)
    return output


def _write_csv(path: Path, records: list[dict[str, Any]]) -> None:
    import csv

    fields = [
        "configuration", "question_id", "question_type", "question", "expected_doc_ids",
        "retrieved_doc_ids", "document_recall_at_k", "complete_document_recall_at_k",
        "hit_at_k", "mrr_at_k", "chunk_precision_at_k", "unique_sources_at_k",
        "source_coverage_policy",
    ]
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for row in records:
            writer.writerow({
                **row,
                "expected_doc_ids": json.dumps(row["expected_doc_ids"]),
                "retrieved_doc_ids": json.dumps(row["retrieved_doc_ids"]),
            })


def _write_summary(path: Path, result: dict[str, Any]) -> None:
    manifest = result["corpus_manifest"]
    lines = [
        "# EnterpriseRAG-Bench source-coverage experiment",
        "",
        f"- Run: `{result['run_id']}`",
        f"- Corpus: {manifest['document_count']:,} documents / {manifest['chunk_count']:,} chunks; "
        f"source slices: {', '.join(manifest['source_files'])}",
        f"- Supported questions: {result['supported_questions']} (all annotated gold document IDs present)",
        f"- Question fixture SHA-256: `{result['question_file_sha256']}`",
        f"- Retrieval: SQLite FTS5 BM25, candidate@{result['index']['candidate_k']}, "
        f"context@{result['index']['top_k']} (build {result['index']['build_seconds']:.1f}s; "
        f"retrieve {result['index']['retrieval_seconds']:.1f}s)",
        "",
        "| Policy | Doc recall | Complete evidence set | Gold-doc chunk share | Unique documents@k |",
        "|---|---:|---:|---:|---:|",
    ]
    for name, metrics in result["configurations"].items():
        lines.append(
            f"| {name} | {metrics['document_recall_at_k']:.3f} | "
            f"{metrics['complete_document_recall_at_k']:.3f} | "
            f"{metrics['chunk_precision_at_k']:.3f} | {metrics['unique_sources_at_k']:.2f} |",
        )
    lines.extend(["", "## Paired bootstrap differences vs global BM25", ""])
    for name, metrics in result["paired_bootstrap_differences_vs_global_bm25"].items():
        diff = metrics["document_recall_at_k_difference"]
        ci = metrics["document_recall_at_k_difference_95pct_bootstrap_ci"]
        multi = metrics["multi_gold_document_recall_at_k_difference"]
        multi_ci = metrics["multi_gold_document_recall_at_k_difference_95pct_bootstrap_ci"]
        lines.append(
            f"- `{name}` overall document-recall difference: {diff:+.3f}, 95% CI [{ci[0]:+.3f}, {ci[1]:+.3f}]; "
            f"multi-gold subset: {multi:+.3f}, 95% CI [{multi_ci[0]:+.3f}, {multi_ci[1]:+.3f}].",
        )
    lines.extend([
        "",
        "## Multi-document retrieval results",
        "",
        "| Policy | Queries | Document recall@k | Complete evidence set@k | Gold-doc chunk share@k |",
        "|---|---:|---:|---:|---:|",
    ])
    for name, metrics in result["configurations"].items():
        multi = metrics["by_gold_source_count"].get("multi_gold_source", {})
        lines.append(
            f"| {name} | {multi.get('queries', 0)} | {multi.get('document_recall_at_k', 0):.3f} | "
            f"{multi.get('complete_document_recall_at_k', 0):.3f} | {multi.get('chunk_precision_at_k', 0):.3f} |",
        )
    lines.extend(["", "## Scope and limitations", "", *[f"- {item}" for item in result["limitations"]], ""])
    path.write_text("\n".join(lines), encoding="utf-8")


def _finalize_existing_run(run_dir: Path) -> None:
    result = json.loads((run_dir / "results.json").read_text(encoding="utf-8"))
    _write_csv(run_dir / "metrics.csv", result["per_question"])
    _write_summary(run_dir / "summary.md", result)
    print(f"Finalized {run_dir}")


def _run(args: argparse.Namespace) -> Path:
    corpus_root = Path(args.corpus_root).resolve() if args.corpus_root else Path(args.archive).resolve().parent
    question_path = Path(args.questions).resolve()
    question_hash = _sha256(question_path)
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    output_root = Path(args.output_root) if args.output_root else BACKEND_DIR / "data" / "eval_enterprise_coverage"
    output_dir = output_root / run_id
    output_dir.mkdir(parents=True, exist_ok=True)

    database_path = Path(args.reuse_index).resolve() if args.reuse_index else output_dir / "bm25_index.sqlite"
    index_started = time.perf_counter()
    if args.reuse_index:
        if not database_path.is_file():
            raise FileNotFoundError(f"Index file does not exist: {database_path}")
        corpus_manifest = _describe_index(corpus_root, database_path, args.source_limit)
    else:
        corpus_manifest = _build_index(corpus_root, database_path, args.source_limit, args.archive)
    extraction_manifest_path = next(corpus_root.glob("*_slice_*/extraction_manifest.json"), None)
    if extraction_manifest_path is not None:
        extraction_manifest = json.loads(extraction_manifest_path.read_text(encoding="utf-8"))
        corpus_manifest["dataset_archive_sha256"] = extraction_manifest.get("archive_sha256")
        if args.source_limit is None:
            corpus_manifest["unique_document_id_count"] = extraction_manifest.get("unique_document_id_count")
            corpus_manifest["duplicate_document_id_instances"] = extraction_manifest.get("duplicate_document_id_instances")
    elif args.archive is not None:
        corpus_manifest["dataset_archive_sha256"] = _sha256(Path(args.archive))
    index_seconds = round(time.perf_counter() - index_started, 3)
    connection = sqlite3.connect(database_path)
    try:
        present_ids = _document_rows(connection)
        questions = [
            json.loads(line)
            for line in question_path.read_text(encoding="utf-8-sig").splitlines()
            if line.strip()
        ]
        supported = [
            row for row in questions
            if row.get("expected_doc_ids")
            and {str(doc_id) for doc_id in row["expected_doc_ids"]}.issubset(present_ids)
        ]
        candidate_k = max(args.top_k, args.candidate_k)
        retrieval_started = time.perf_counter()
        records, supported_count = _evaluate_ranked(supported, connection, args.top_k, candidate_k)
        retrieval_seconds = round(time.perf_counter() - retrieval_started, 3)
    finally:
        connection.close()

    aggregates = _aggregate(records)
    paired = _paired_intervals(records, "global_bm25_topk")
    type_counts = Counter(str(row.get("question_type", "unknown")) for row in supported)
    heuristic_records = {
        row["question_id"]: row
        for row in records
        if row["configuration"] == "intent_routed_source_diverse"
    }
    true_multi = sum(len(row["expected_doc_ids"]) > 1 for row in heuristic_records.values())
    predicted_multi = sum(bool(row["source_coverage_policy"]) for row in heuristic_records.values())
    true_positive = sum(
        len(row["expected_doc_ids"]) > 1 and bool(row["source_coverage_policy"])
        for row in heuristic_records.values()
    )
    route_precision = true_positive / predicted_multi if predicted_multi else 0.0
    route_recall = true_positive / true_multi if true_multi else 0.0
    result = {
        "run_id": run_id,
        "benchmark": (
            "EnterpriseRAG-Bench v1.0.0 complete document corpus"
            if corpus_manifest["document_count"] >= 500_000
            else "EnterpriseRAG-Bench v1.0.0 answerable questions with gold documents in a sampled corpus"
        ),
        "question_file": question_path.name,
        "question_file_sha256": question_hash,
        "corpus_root": corpus_root.name,
        "corpus_manifest": corpus_manifest,
        "supported_questions": supported_count,
        "candidate_questions_with_gold_docs": len(supported),
        "question_types": dict(sorted(type_counts.items())),
        "intent_router_vs_multi_gold": {"gold_multi_source_queries": true_multi, "routed_queries": predicted_multi, "true_positive": true_positive, "precision": round(route_precision, 6), "recall": round(route_recall, 6)},
        "index": {"chunking": "InsightEdge chunk_text; 1400 character chunks; 280 character overlap", "retrieval": "SQLite FTS5 BM25 over chunks", "candidate_k": candidate_k, "top_k": args.top_k, "build_seconds": index_seconds, "retrieval_seconds": retrieval_seconds, "index_reused": bool(args.reuse_index)},
        "configurations": aggregates,
        "paired_bootstrap_differences_vs_global_bm25": paired,
        "limitations": [
            "Only questions with annotated expected_doc_ids are scored; the high_level and info_not_found items without document-ID labels are excluded.",
            "Expected document IDs are gold at the document level, not at the chunk level; gold-document chunk share is a proxy and does not establish passage-level entailment.",
            "This experiment isolates chunk retrieval and source selection; it does not evaluate language-model answer correctness or citation entailment.",
            "The experiment uses SQLite FTS5 BM25; InsightEdge serving also uses dense-priority hybrid candidates, so the BM25 results do not directly establish end-to-end hybrid gains.",
            "A bounded selector can still trade chunk precision for source recall; retrieval labels do not establish answer correctness or citation entailment.",
        ],
        "per_question": records,
    }
    (output_dir / "results.json").write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    _write_csv(output_dir / "metrics.csv", records)
    _write_summary(output_dir / "summary.md", result)
    print(output_dir)
    print(json.dumps({"questions": supported_count, "chunks": corpus_manifest["chunk_count"], "configurations": aggregates, "paired": paired}, indent=2))
    return output_dir


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Evaluate document coverage on an EnterpriseRAG-Bench subset.")
    parser.add_argument("--finalize-existing", default=None, help="Rebuild CSV and summary files from results.json in this run directory.")
    parser.add_argument("--corpus-root", default=None, help="Directory containing <source>_slice_0001/<source>/*.txt archives.")
    parser.add_argument("--archive", default=None, type=Path, help="Read .txt members directly from all_documents.zip instead of the extracted files.")
    parser.add_argument("--questions", default=None, help="EnterpriseRAG-Bench questions.jsonl from release v1.0.0.")
    parser.add_argument("--output-root", default=None)
    parser.add_argument("--top-k", type=int, default=8)
    parser.add_argument("--candidate-k", type=int, default=100)
    parser.add_argument("--source-limit", type=int, default=None, help="Optional deterministic limit on sorted source files for smoke runs.")
    parser.add_argument("--reuse-index", default=None, help="Reuse a compatible FTS index rather than rebuilding it.")
    args = parser.parse_args()
    if args.finalize_existing:
        return args
    if args.archive is not None and not args.archive.is_file():
        parser.error(f"--archive does not exist: {args.archive}")
    if (not args.corpus_root and not args.archive) or not args.questions:
        parser.error("--questions and either --corpus-root or --archive are required unless --finalize-existing is used")
    if args.top_k <= 0 or args.candidate_k < args.top_k:
        parser.error("--top-k must be positive and --candidate-k must be >= --top-k")
    return args


if __name__ == "__main__":
    parsed_args = _parse_args()
    if parsed_args.finalize_existing:
        _finalize_existing_run(Path(parsed_args.finalize_existing))
    else:
        _run(parsed_args)
