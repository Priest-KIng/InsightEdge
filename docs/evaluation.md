# InsightEdge Evaluation Guide

## Purpose

The benchmark is a repeatable, local-only regression harness for structure-aware retrieval, adaptive routing, and citation provenance. It is intentionally small and must not be used to claim broad generalization or state-of-the-art performance.

## Fixture Corpus

Fixtures live under backend/eval/fixtures/.

- prose.txt: local privacy, ChromaDB, SQLite, workspaces, and Ollama prose.
- table.md: Markdown headings and a model comparison table.
- citation_rich.md: citation fields, evidence protocol, and explicit limitations.
- ocr_marker.txt: an OCR-marked text fixture for metadata propagation.
- questions.json: expected sources, snippets, query types, required terms, and a weak-evidence case.

## Baselines and Routing

The default run compares dense, lexical, hybrid, hybrid_rerank, hybrid_compression, and router configurations. Reranking remains a local optional path and is a no-op when CROSS_ENCODER_MODEL is not configured.

The router is deterministic and classifies factual lookup, summarization, compare/contrast, table/structured-data, OCR/scanned-document, multi-document synthesis, ambiguous/underspecified, and greeting/meta questions. It records the selected retrieval mode, model tier, complexity score, and rationale.

Feature ablations are controlled with:

- --no-retrieval-router and --no-model-router
- --no-hyde and --no-multi-query
- --no-reranking, --compression, and --parent-document

## Metrics

Each run computes Recall@k, MRR, nDCG@k, context precision, context recall, citation precision, source correctness, chunk correctness, groundedness, ingestion success rate, OCR marker rate, and ingestion/query P50/P95 latency.

Groundedness is deterministic term and overlap matching. It is a regression signal, not a human annotation or full faithfulness judge.

## Command and Artifacts

From backend, run:

    python scripts/evaluate_rag.py

Outputs are written to backend/data/eval_runs/<timestamp>/:

- results.json: complete configuration, ingestion timing, and per-question rows.
- metrics.csv: tabular per-question metrics.
- summary.md: comparative table and observed discussion.

The run does not call hosted APIs and does not download models or documents.

## Reproducibility

Use the project virtual environment, install backend/requirements.txt, ensure the local embedding model is available, and run the benchmark with a fixed local configuration. Record the Ollama model list, hardware, and environment variables beside any report result.

## Reporting Guidance

The defensible contribution is a local-first RAG prototype with structure-aware retrieval, adaptive routing, and provenance-grounded answers evaluated using repeatable local retrieval baselines and citation-focused metrics.
