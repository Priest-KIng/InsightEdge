# InsightEdge — Improvement Checklist

Priority tiers: **P0** = showstopper / broken right now · **P1** = critical for daily use · **P2** = important quality-of-life · **P3** = enhancement · **P4** = long-term / research

---

## P0 — Bugs (Broken Right Now)

- [x] **Chat endpoint mismatch** — Frontend calls `POST /api/chat/ask` but the backend registers the route at `POST /api/chat` (no `/ask` suffix). Every chat message returns a 404. Fix: change `fetchWithTimeout` URL in `App.jsx` from `/chat/ask` to `/chat`.

- [x] **No file-type validation on upload** — `POST /api/ingest/files` accepts any file. Files with unsupported extensions are silently saved to disk, then skipped during `_ingest_files`, wasting disk space and leaving stale upload artifacts. Fix: validate `file.content_type` / extension before persisting.

- [x] **Ingest job progress is never updated incrementally** — `files_processed`, `chunks_indexed`, and `skipped_files` counters remain at `0` throughout the `running` state and only flip to final values on `completed`. The frontend spinner gives no real progress signal. Fix: call `_set_job_state` after each file inside `_run_ingest_job`.

- [x] **Duplicate chunks on re-ingest** — Every ingest call generates fresh `uuid4()` IDs, so re-uploading the same document appends duplicate chunks rather than replacing old ones. Fix: derive chunk IDs from `hash(file_path + chunk_index)` so `upsert` overwrites existing vectors.

- [x] **Sentence chunker does not guard against oversized sentences** — A single sentence longer than `CHUNK_SIZE` is appended to `current_chunk` without splitting, silently producing a chunk that exceeds the configured limit and can overflow the embedding model's token window. Fix: add a hard character-split fallback for sentences that exceed `chunk_size`.

- [x] **Stale `backend/backend/data/` directory** — A nested `backend/backend/data/chroma` and `backend/backend/data/uploads/` exist alongside the correct `backend/data/`. These appear to be artefacts of an incorrect working directory during an early run. They should be deleted to avoid confusion about which ChromaDB is actually being used.

- [x] **No `.env.example` file** — Config documentation references a `.env` file but no template ships with the repo. New contributors have no reference for required keys.

---

## P1 — Critical for Reliable Daily Use

- [x] **Tesseract and Poppler are undocumented external dependencies** — PDF OCR will silently produce empty pages or log warnings if `tesseract` and `poppler` (for `pdf2image`) are not installed on the host OS. These must be documented in the README with installation commands for Windows, macOS, and Linux.

- [x] **In-memory chat sessions lost on restart** — `CHAT_SESSIONS` is a plain dict. A server restart wipes all conversation history. Fix: persist sessions to SQLite (or the existing `backend/data/` directory) using a lightweight store.

- [x] **In-memory ingest job registry lost on restart** — Same issue as sessions. If the server restarts mid-ingest the job is orphaned and its status can never be retrieved. Fix: persist job state alongside sessions.

- [x] **`lru_cache` on `get_rag_service` prevents recovery from errors** — If `RAGService.__init__` raises during startup (e.g. Chroma lock, model download failure), the cached exception prevents any subsequent request from retrying. Fix: use a manual singleton with explicit re-initialisation on failure, or replace `lru_cache` with a FastAPI lifespan dependency.

- [x] **No knowledge-base management endpoint** — There is no API (or UI) to list, delete, or reset ingested documents. Once a document is ingested it can only be removed by wiping the entire ChromaDB. Fix: add `GET /api/ingest/documents` and `DELETE /api/ingest/documents/{doc_id}` endpoints; expose a "Clear knowledge base" button in the sidebar.

- [x] **No rate limiting or authentication** — The API is fully open. Anyone on the local network can ingest files or query the LLM. Fix: add a configurable bearer-token check via a FastAPI dependency (even a single shared `API_KEY` env var is a significant improvement).

- [x] **Chat history window is unlimited in the frontend `conversation` state** — The server trims stored history to 40 turns, but the local React `conversation` array grows indefinitely, causing the chat UI to slow down for very long sessions. Fix: cap displayed turns or implement a "load earlier" pagination pattern.

- [x] **LLM timeout hard-coded to 120 s** — For large context windows or slow hardware 120 s is frequently exceeded. Fix: expose as a `LLM_TIMEOUT_SECONDS` env variable with a sensible default (180–300 s).

---

## P2 — Important Quality-of-Life

- [ ] **Streaming LLM responses** — The UI waits for the full answer before rendering anything. Ollama supports streaming via `stream: true`. Fix: switch `LocalLLMService.generate` to yield tokens using an SSE or chunked-transfer response and render them progressively in the frontend.

- [ ] **No document list in the UI** — The sidebar shows upload controls but not a list of what has already been ingested. Users cannot tell what the knowledge base contains. Fix: return source file names from `GET /api/ingest/documents` and render them in the sidebar.

- [ ] **Abbreviation false-splits in chunker** — `re.split(r"(?<=[.!?])\s+", ...)` splits on "Dr. Smith", "U.S. economy", version numbers, etc. Fix: use a sentence-boundary detector such as `nltk.sent_tokenize` or `spacy`'s sentencizer, or at minimum add a negative-lookbehind for common abbreviations.

- [ ] **No hybrid search (keyword + vector)** — Pure vector search misses exact keyword matches (product codes, proper nouns, numeric IDs). Fix: add a BM25 pre-filter using `rank_bm25` or ChromaDB's full-text search, then fuse results using Reciprocal Rank Fusion (RRF) before the distance filter.

- [ ] **Citations show raw file-system paths** — The UI renders absolute server-side paths like `E:\Projects\InsightEdge\backend\data\uploads\<uuid>.pdf`, which are meaningless to the user. Fix: store the original `file.filename` in chunk metadata at ingest time and return that as `source` in citations.

- [ ] **No progress feedback for large file uploads** — Large file uploads have no progress bar; the UI just shows "Uploading files…". Fix: use `XMLHttpRequest` with `upload.onprogress` or the Fetch API streaming body.

- [ ] **Single-threaded ingest** — `asyncio.to_thread` runs one `_ingest_files` call in a single thread. For batches of many files this blocks the thread-pool slot for the full duration. Fix: split the file list and run ingest in a `ProcessPoolExecutor` or add a proper task queue (e.g. `arq` or `dramatiq`).

- [ ] **No configurable system prompt** — The LLM system prompt is hardcoded in `LocalLLMService.generate`. Different documents (legal, medical, technical) benefit from domain-specific instructions. Fix: expose a `SYSTEM_PROMPT` env variable and an optional per-session override from the UI.

- [ ] **Dark/light theme preference not persisted** — Theme resets to `light` on every page reload. Fix: persist to `localStorage`.

- [ ] **Mobile layout broken** — The sidebar is hidden on small screens (`hidden md:flex`) with no alternative navigation. Fix: add a hamburger menu or slide-in drawer for mobile.

---

## P3 — Enhancements

- [ ] **Cross-encoder re-ranking** — Vector similarity is a weak relevance signal; semantically similar but factually irrelevant chunks are returned. Fix: after vector retrieval, re-rank with a cross-encoder (e.g. `cross-encoder/ms-marco-MiniLM-L-6-v2`) and keep only the top-N after re-scoring.

- [ ] **Contextual compression / excerpt extraction** — Sending full 1400-char chunks to the LLM wastes context tokens. Fix: use an LLM call or extractive summariser to distill only the relevant sentences from each retrieved chunk before building the final prompt.

- [ ] **Multiple knowledge-base collections / workspaces** — All documents share a single ChromaDB collection. Fix: allow users to create named workspaces; each chat session selects which workspace to query.

- [ ] **Support more file formats** — `.csv`, `.xlsx`, `.html`, `.epub`, `.pptx` are commonly encountered but unsupported. Fix: add loaders for each using `pandas`, `openpyxl`, `BeautifulSoup4`, and `python-pptx`.

- [ ] **Ingest from URL** — Add `POST /api/ingest/url` that fetches a web page, strips HTML, and ingests the clean text.

- [ ] **Export conversation** — Add a "Download chat" button that exports the session as Markdown or JSON.

- [ ] **Health check includes model status** — `GET /api/health` only returns `"ok"`. Fix: ping Ollama and verify the embedding model is loaded; return degraded status if either is unavailable.

- [ ] **Structured logging and request IDs** — Replace bare `logger.warning` calls with structured JSON logs (using `structlog`) and inject a per-request trace ID for easier debugging.

- [ ] **Chunk deduplication at query time** — If the same source chunk appears in multiple results (possible with overlapping windows) it inflates context. Fix: deduplicate by chunk text hash before building the prompt.

- [ ] **DOCX image extraction** — `python-docx` currently only extracts paragraph text. Images and diagrams in `.docx` files are silently ignored. Fix: iterate `doc.inline_shapes` and run OCR on each extracted image.

---

## P4 — Model & Retrieval Research

### Embedding Model

- [ ] **Upgrade to `BAAI/bge-large-en-v1.5`** — Same family as the current model but significantly higher retrieval accuracy on MTEB benchmarks. Doubles memory footprint (~1.3 GB) but meaningfully improves recall for longer, more complex queries. Worth enabling on machines with ≥ 8 GB RAM.

- [ ] **Switch to `BAAI/bge-m3`** — ColBERT-style late-interaction and multi-lingual support. Provides dense + sparse + multi-vector retrieval in one model. Best overall retrieval quality if the hardware can support it. Use `FlagEmbedding` library for access to its full feature set.

- [ ] **Evaluate `nomic-embed-text`** — Runs inside Ollama (no Python model download), context window up to 8192 tokens, strong performance on long documents. Simplifies the stack by removing `sentence-transformers` dependency.

- [ ] **Evaluate `mxbai-embed-large`** — Outperforms `bge-large` on many document retrieval tasks at similar size; also available via Ollama.

### LLM Model

- [ ] **Upgrade to `llama3.1:70b-instruct-q4_K_M`** — 70B at 4-bit quantization requires ~40 GB VRAM/RAM but handles complex multi-hop reasoning, table understanding, and long-context tasks substantially better than 8B.

- [ ] **Try `phi4:14b`** — Microsoft Phi-4 14B is optimised for reasoning and document Q&A; outperforms Llama 3.1 70B on many knowledge tasks at a fraction of the cost. Pull with `ollama pull phi4`.

- [ ] **Try `qwen2.5:14b`** — Qwen 2.5 14B has strong multilingual and structured-data (table, JSON) comprehension; a good choice if the corpus contains non-English documents or heavy spreadsheet data.

- [ ] **Try `mistral-small3.1`** — Latest Mistral 24B; strong instruction following and long-context recall. Available via Ollama.

- [ ] **Use a vision-language model for image-heavy PDFs** — `llava:13b` or `minicpm-v` can receive page images directly rather than relying on OCR text. For scanned documents this is far more reliable. Integration path: render PDF pages to images during ingest and store them alongside text chunks; at query time send relevant page images to the VLM.

### Retrieval & Prompting Improvements

- [ ] **Implement HyDE (Hypothetical Document Embeddings)** — Before retrieving, generate a hypothetical answer to the question using the LLM and embed *that* as the query. The hypothetical answer is often a closer match to the actual document chunks than the raw question.

- [ ] **Parent-document retrieval** — Store small child chunks for retrieval but return the full parent paragraph to the LLM for context. Improves precision while keeping context coherent.

- [ ] **Query expansion / multi-query** — Generate 3–5 semantically varied reformulations of each user question, retrieve for each, merge and deduplicate results. Reduces sensitivity to exact phrasing.

- [ ] **Table-aware prompt engineering** — Add explicit instructions to the system prompt telling the model how to read pipe-delimited table rows (the format produced by `pdfplumber`). Example: "Tables are represented as rows separated by `|`. Treat each row as a record and use column headers from the first row."

- [ ] **Self-RAG / iterative retrieval** — Allow the LLM to decide whether the retrieved context is sufficient and trigger a follow-up retrieval pass if it is not, before producing the final answer.

- [ ] **Fine-tuning (long-term)** — If a consistent domain-specific corpus is expected (e.g. legal contracts, medical notes), fine-tune a base model using [Unsloth](https://github.com/unslothai/unsloth) + QLoRA on domain Q&A pairs. This is complex but provides the largest accuracy gains for narrow, specialised use cases. Recommended base: `Meta-Llama-3.1-8B` or `Phi-4-14B`.

---

## Quick-Win Summary (Highest Impact / Lowest Effort)

| # | Item | Effort | Impact |
|---|------|--------|--------|
| 1 | Fix `/chat/ask` → `/chat` URL in frontend | 1 min | P0 critical |
| 2 | Add Tesseract + Poppler install docs | 15 min | P1 |
| 3 | Hash-based chunk IDs (fix duplicates) | 30 min | P0 |
| 4 | Persist original filename in citations | 20 min | P2 |
| 5 | Expose `LLM_TIMEOUT_SECONDS` env var | 10 min | P1 |
| 6 | Add `.env.example` | 10 min | P1 |
| 7 | Persist theme to `localStorage` | 5 min | P2 |
| 8 | Delete stale `backend/backend/` directory | 1 min | P0 |
| 9 | Switch to `phi4:14b` in Ollama | 5 min (+ download) | P4 high ROI |
| 10 | Add cross-encoder re-ranking | 2–3 hrs | P3 high ROI |
