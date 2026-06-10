# Report Notes For Publication Draft

## Honest Contribution Statement

InsightEdge can be described as a local-first RAG prototype that combines offline document ingestion, workspace-isolated vector retrieval, local Ollama inference, structured citation provenance, and a repeatable fixture benchmark for comparing local retrieval modes.

Do not claim a novel algorithm or state-of-the-art result. The implemented contribution is engineering and evaluation oriented: citation-grounded provenance and reproducible local retrieval baselines in a privacy-preserving RAG workflow.

## Experimental Setup

- Hardware: `[NEEDS USER INPUT]`
- Operating system: `[NEEDS USER INPUT]`
- Backend: FastAPI, ChromaDB, SQLite, sentence-transformers, Ollama integration.
- Frontend: React and Vite.
- Default embedding model: `BAAI/bge-small-en-v1.5`.
- Default LLM model: `llama3.1:8b-instruct-q4_K_M`.
- Dataset: checked-in fixture corpus under `backend/eval/fixtures/`.
- Baselines: dense, lexical, hybrid, and hybrid with compression.
- Metrics: Recall@k, MRR, nDCG@k, context precision/recall, citation precision, groundedness heuristic, ingestion success rate, OCR marker rate, and P50/P95 query latency.

## Results

Run:

```powershell
cd backend
python scripts/evaluate_rag.py --preset quick
```

Then use only numbers from the generated `backend/data/eval_runs/<timestamp>/summary.md`, `metrics.csv`, and `results.json`.

Latest verified run during this implementation wrote artifacts to:

```text
backend/data/eval_runs/20260610T103433Z/
```

Measured summary from that run:

| Mode | Recall@k | MRR | nDCG@k | Context Precision | Citation Precision | Groundedness | P50 Query ms | P95 Query ms |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| dense | 1.000 | 1.000 | 1.000 | 0.833 | 0.833 | 1.000 | 28.61 | 34.58 |
| lexical | 1.000 | 0.833 | 0.877 | 0.333 | 0.333 | 1.000 | 2.28 | 15.35 |
| hybrid | 1.000 | 1.000 | 1.000 | 0.833 | 0.833 | 1.000 | 18.40 | 25.34 |
| hybrid_compression | 1.000 | 1.000 | 1.000 | 0.833 | 0.833 | 1.000 | 16.40 | 16.75 |

Ingestion success rate for the fixture corpus was `1.000` with ingestion latency `1751.39 ms`.

## Limitations

- The benchmark corpus is small and local to the repository.
- The groundedness score is a deterministic required-term heuristic.
- OCR confidence is not available from the text fixture.
- The system depends on local model availability and local hardware capacity.
- The project does not compare against hosted commercial RAG services because the product goal is privacy-preserving local execution.
- URL ingestion has been removed to preserve the file-only local-first product workflow.

## Reproducibility

Use the README setup commands, pull the local Ollama model, install OCR dependencies if scanned PDFs are required, then run:

```powershell
cd backend
python -m compileall app scripts
python -m pytest
python scripts/evaluate_rag.py --preset quick
```

For a live end-to-end proof, start the backend and run:

```powershell
python scripts/smoke_e2e.py --workspace e2e-file-only-proof
```
