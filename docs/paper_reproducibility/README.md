# InsightEdge paper reproducibility bundle

This bundle preserves per-query outputs behind the paper's reported numbers. It complements, rather than replaces, the scripts and question fixture in `backend/`.

## Included runs

- `retrieval_16_20261111T083609Z/`: four checked-in fixture documents, 13 indexed chunks, 16 labeled questions, and six retrieval configurations. It includes `results.json`, `metrics.csv`, and `summary.md`.
- `scope_24_20261111T083539Z/`: deterministic synthetic corpus of 24 near-duplicate one-chunk reports; 24 filename-scoped queries; generation disabled. It includes allowed document IDs, retrieved IDs, citations projected from each result, contract checks, and timing observations.
- `live_phi3_20261111/`: five local `phi3:mini` service-level prompts over three temporary documents, with exact question, answer, citation source names, refusal flag, route, groundedness signal, and response latency.

The question fixture is `backend/eval/fixtures/questions_paper.json`; SHA-256: `f40540dc63f750c08b4464d42687ecc9bcefee9df178426915cf2ee416b9d433`.

## Re-run

From the `backend` directory, with the configured embedding dependencies available locally:

```powershell
.\.venv\Scripts\python.exe scripts\evaluate_rag.py --questions eval\fixtures\questions_paper.json --modes dense,lexical,hybrid,hybrid_rerank,hybrid_compression,router --output-root data\eval_runs_paper_final_v2
.\.venv\Scripts\python.exe scripts\evaluate_scope_contract.py --output-root data\eval_scope_runs_final
.\.venv\Scripts\python.exe -m pytest -q
```

The retrieval runner does not call the language model. Scope latency is descriptive and not a speed claim; the synthetic corpus intentionally creates source-confusable candidates. The live model run is recorded as an observed service-level smoke test, not a repeated or statistically powered evaluation.
