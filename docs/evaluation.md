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

Hybrid retrieval now builds an independent BM25-style lexical ranking across the filtered workspace corpus and unions those candidates with dense results. High-coverage lexical matches can therefore be recovered when dense search omits them; common words and low-coverage matches are excluded. Candidates found by both paths keep their dense ordering, while a lexical-only candidate can backfill the requested result set. This is a practical candidate-recall change, not a claim that hybrid retrieval improves answer quality in general. The small fixture run below did not show an aggregate quality gain.

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

## Research Context and Current Evidence

HyDE generates hypothetical documents to improve retrieval for queries whose wording differs from the source; it is an optional local Ollama path, not enabled by default ([Gao et al., 2022](https://arxiv.org/abs/2212.10496)). RAGChecker and ARES describe broader evaluation approaches that use fine-grained diagnostics and model-based judges ([RAGChecker](https://arxiv.org/abs/2408.08067), [ARES](https://arxiv.org/abs/2311.09476)). The current checked-in fixture is far too small to support those kinds of general claims.

An exploratory run on the four checked-in documents and five queries measured dense vs. hybrid Recall@k of 0.800 vs. 0.800, MRR of 0.800 vs. 0.800, and context precision of 0.533 vs. 0.533. Hybrid P50 latency in that run was 21.36 ms vs. 17.17 ms for dense. This indicates no retrieval quality gain on the current fixtures and a small latency cost; it is not evidence of a general improvement. A controlled unit test verifies the specific intended behavior: an exact project identifier is retrieved from the lexical corpus when it is absent from the simulated dense candidate list.

For a paper-worthy contribution, the next experiment should compare dense, BM25, fixed RRF, the current high-coverage lexical backfill, HyDE, and query-adaptive combinations over multiple organizations' document types, with document-level train/dev/test splits, annotated relevance, answer faithfulness, privacy/egress checks, and latency/compute reporting. Tune thresholds only on dev data and report confidence intervals and per-query failure cases. A hosted structured-decision model such as Jev should be an opt-in public-data baseline only: it adds external processing and cost, so it does not fit the default organization-private path ([Jev documentation](https://docs.typesafe.ai/models)).
