# Publication Readiness Audit

## Implemented Evidence

- Loader-level structural segments preserve headings, bullets, tables, page/slide markers, OCR flags, section titles, and offsets.
- Chroma metadata carries document ID, chunk ID, filename, source type, page/slide, section, block type, table/OCR flags, snippets, and offsets.
- Deterministic routing records query type, complexity, rationale, retrieval mode, candidate count, and model tier.
- Chat responses and SSE final events expose model, workspace, retrieval, request ID, latency, groundedness, confidence, refusal state, and structured citations.
- Weak retrieval returns an explicit evidence refusal that names the current workspace rather than telling users to upload documents when files already exist.
- The local benchmark emits JSON, CSV, and Markdown artifacts with baselines, routing configuration, ablation toggles, correctness metrics, OCR rate, and P50/P95 latency.
- SQLite retains WAL, busy timeout, backward-compatible timestamp migrations, and indexed workspace/job lookup paths.

## Verification Required Before Publication

- Run the benchmark on the target machine and archive its generated artifacts.
- Record exact Ollama versions, installed models, GPU memory, OCR dependency versions, and environment variables.
- Review answer verification against a human-labeled sample; heuristic groundedness is not sufficient evidence of general faithfulness.
- Expand the fixture corpus and expected source/chunk labels before making claims beyond regression evidence.

## Known Limitations

- Small fixture dataset.
- Local hardware and VRAM constraints.
- OCR dependency variability.
- Heuristic groundedness and refusal thresholds.
- No cloud-scale comparison.
- No claim of state-of-the-art performance.
