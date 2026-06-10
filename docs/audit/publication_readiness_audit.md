# Publication Readiness Audit

## Critical Bug

- URL ingestion was still exposed in the backend and frontend even though the current product direction is local file-only knowledge ingestion. The `/api/ingest/url` route, request schema, RAG URL ingest method, and UI controls were removed.
- Lexical evaluation mode originally still executed dense retrieval before lexical ranking. It now reads workspace chunks directly and ranks by local token overlap.

## High Priority Improvements

- Structured citation provenance was expanded to include document ID, chunk ID, filename/source, page number when available, section hints, snippets, retrieval rank, score, source type, OCR marker, and character offsets.
- Chat responses now return model, workspace ID, retrieval mode, retrieved chunk counts, final context counts, latency, and request ID.
- Workspace deletion was added for non-default workspaces, including Chroma collection removal and SQLite chat-state cleanup.
- Frontend workspace creation and destructive actions now use inline controls rather than browser prompt/confirm flows.
- Optional local API-key support was added to the frontend.

## Publication Blockers Addressed

- A repeatable local fixture benchmark was added under `backend/eval/fixtures/`.
- `backend/scripts/evaluate_rag.py` exports JSON, CSV, and Markdown artifacts with retrieval, citation, groundedness, ingest, OCR-marker, and latency metrics.
- README and evaluation notes now describe file-only local ingestion and measured claims.

## Remaining Publication Gaps

- The fixture dataset is intentionally small and should be expanded before making claims beyond regression evidence.
- OCR confidence is not measured; the current fixture only verifies OCR-derived metadata propagation.
- Answer faithfulness is measured with a heuristic, not human annotation or a robust judge model.
- Hardware information, exact model versions installed through Ollama, and screenshots still require human review for the final paper.
- Workspace rename and ingest cancellation are not implemented in this pass.

## Nice-To-Have Enhancements

- Larger manually labeled benchmark corpus.
- Human-reviewed answer quality annotations.
- UI side panel with exact citation span highlighting.
- Optional local reranker benchmark when a cross-encoder model is configured.
