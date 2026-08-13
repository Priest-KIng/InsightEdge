# Report Notes For Publication Draft

## Honest Contribution Statement

We present a local-first RAG prototype with structure-aware retrieval, adaptive routing, and provenance-grounded answers, evaluated using repeatable local retrieval baselines and citation-focused metrics.

This is an engineering and evaluation contribution. It does not claim a novel learning algorithm or state-of-the-art performance.

## Experimental Setup

- Backend: FastAPI, ChromaDB, SQLite, sentence-transformers, and Ollama.
- Frontend: React and Vite.
- Embeddings: BAAI/bge-small-en-v1.5 by default.
- Generation: phi3:mini by default, with optional installed local model tiers.
- GPU: Ollama receives automatic GPU offload for the default 4 GB-friendly model; the stronger tier defaults to CPU fallback to avoid VRAM overcommit.
- Dataset: checked-in fixtures under backend/eval/fixtures/.
- Baselines: dense, lexical, hybrid, reranked, compressed, and routed retrieval.
- Metrics: retrieval ranking, context/citation correctness, groundedness heuristic, ingestion/OCR rates, and P50/P95 latency.

Record exact hardware, operating system, Ollama model list, embedding cache state, and environment variables for every reported run.

## Reproduction

From backend:

    python -m compileall app scripts
    python -m pytest
    python scripts/evaluate_rag.py

The generated backend/data/eval_runs/<timestamp>/results.json, metrics.csv, and summary.md are the only source for numerical claims. Do not copy example numbers into the report without a new run.

## Limitations

- The fixture corpus is small and repository-local.
- Local GPU and CPU memory constrain model size and latency.
- OCR behavior depends on external Tesseract and Poppler installation.
- Groundedness and answer verification use heuristics and are not human-annotated.
- There is no cloud-scale or hosted-service comparison.
- The prototype does not establish broad generalization.
