# InsightEdge Evaluation Guide

## Purpose

The local benchmark provides repeatable evidence for retrieval and citation behavior without using cloud services or paid APIs. It is intentionally small and fixture-based, so it should be described as a regression and publication-support benchmark rather than a broad external evaluation.

## Fixture Corpus

Fixtures are stored under `backend/eval/fixtures/`.

| File | Purpose |
| --- | --- |
| `documents/prose.txt` | Prose document covering local privacy, ChromaDB, SQLite, workspaces, and Ollama. |
| `documents/table.md` | Markdown table covering model roles and lexical baseline evidence. |
| `documents/ocr_marker.txt` | Text fixture containing an `[OCR]` marker to verify OCR-derived provenance flow. |
| `questions.json` | Labeled questions with expected source files and required answer terms. |

## Baselines

The quick preset evaluates:

- Dense retrieval.
- Lexical retrieval using local token-overlap ranking.
- Hybrid retrieval using dense candidates and lexical rank fusion.
- Hybrid retrieval with extractive context compression.

Optional reranking can be evaluated by configuring `CROSS_ENCODER_MODEL` and running a mode that includes `hybrid_rerank`.

## Metrics

The script exports:

- Recall@k.
- MRR.
- nDCG@k.
- Context precision and context recall.
- Citation precision.
- Required-term groundedness heuristic.
- Ingestion success rate.
- OCR marker rate.
- Query latency with P50/P95 summary.

The groundedness value is a deterministic required-term check over retrieved context. It is not a human evaluation and should not be presented as a full faithfulness judge.

## Command

```powershell
cd backend
python scripts/evaluate_rag.py --preset quick
```

Outputs are written to:

```text
backend/data/eval_runs/<timestamp>/
```

Each run contains:

- `results.json`
- `metrics.csv`
- `summary.md`

## Reporting Guidance

Use only numbers from generated benchmark artifacts. The defensible contribution is:

> A local-first RAG prototype with evaluated citation-grounded provenance and repeatable local retrieval baselines.

Do not claim state-of-the-art performance, broad generalization, or production-grade OCR accuracy from this fixture benchmark.
