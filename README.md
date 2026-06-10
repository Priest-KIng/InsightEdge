# InsightEdge

InsightEdge is a privacy-first local Retrieval-Augmented Generation system. It ingests local files, embeds and indexes them locally, retrieves evidence from a workspace-isolated ChromaDB store, and answers questions through a local Ollama model.

## Architecture

1. **Document ingestion** - supports `.txt`, `.md`, `.pdf`, `.docx`, `.csv`, `.xlsx`, `.html`, `.epub`, and `.pptx`; PDFs use `pdfplumber` for text/table extraction with `pytesseract` and `pdf2image` as OCR fallback for scanned pages.
2. **Sentence-aware chunking** - splits on sentence boundaries with configurable `CHUNK_SIZE` and `CHUNK_OVERLAP`.
3. **Embeddings** - defaults to `BAAI/bge-small-en-v1.5` via `sentence-transformers`.
4. **Retrieval** - persistent ChromaDB with dense, lexical, hybrid, and hybrid-with-compression modes for evaluation.
5. **LLM generation** - local Ollama model, defaulting to `llama3.1:8b-instruct-q4_K_M`.
6. **Frontend** - React/Vite UI with file upload, async ingest-job polling, workspace controls, streaming chat, structured citations, exports, and theme persistence.
7. **State** - SQLite stores chat sessions and ingest jobs with WAL mode, timestamps, and indexes.

## Backend Setup

```powershell
cd backend
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

Copy and edit a `.env` file in `backend/` or the project root to override defaults.

## Frontend Setup

```powershell
cd frontend
npm install
npm run dev
```

The frontend runs on `http://localhost:5173` by default. Optionally set `VITE_API_BASE_URL` in `frontend/.env` to point at a non-default backend. If backend `API_KEY` protection is enabled, set `VITE_API_KEY` or enter the token in the app's Local API Token field.

## Ollama Setup

```powershell
ollama pull llama3.1:8b-instruct-q4_K_M
ollama serve
```

## OCR Dependencies

Scanned-PDF OCR requires Tesseract OCR and Poppler.

```powershell
# Windows with Chocolatey
choco install tesseract -y
choco install poppler -y
```

```bash
# macOS
brew install tesseract poppler

# Debian/Ubuntu
sudo apt-get update
sudo apt-get install -y tesseract-ocr poppler-utils
```

Without these dependencies, OCR fallback for scanned PDF pages and embedded PDF images may return empty output.

## API Summary

### Ingest

| Method | Path | Description |
| --- | --- | --- |
| `POST` | `/api/ingest/files` | Upload one or more local files using multipart field `files`; returns an async job ID. |
| `GET` | `/api/ingest/jobs/{job_id}` | Poll ingest job status. |
| `POST` | `/api/ingest/path` | Ingest a server-side path constrained to `INGEST_BASE_DIR`; intended for local developer/admin use. |
| `GET` | `/api/ingest/documents` | List indexed documents for a workspace. |
| `DELETE` | `/api/ingest/documents/{doc_id}` | Delete one indexed document from a workspace. |
| `DELETE` | `/api/ingest/documents` | Clear all indexed documents from a workspace. |
| `GET` | `/api/ingest/workspaces` | List known workspaces. |
| `DELETE` | `/api/ingest/workspaces/{workspace_id}` | Delete a non-default workspace and its local chat state. |

The product workflow is file-only local ingestion. URL/web-page ingestion is not exposed.

### Chat

| Method | Path | Description |
| --- | --- | --- |
| `POST` | `/api/chat` | Ask a question and receive a complete response. |
| `POST` | `/api/chat/stream` | Ask a question and receive Server-Sent Events with a final metadata event. |
| `GET` | `/api/chat/session/{session_id}` | Retrieve workspace-scoped conversation history. |
| `DELETE` | `/api/chat/session/{session_id}` | Clear workspace-scoped conversation history. |

Chat responses include backward-compatible `answer`, `citations`, and `context_chunks` fields plus structured metadata: model, workspace ID, retrieval mode, retrieved/final context counts, latency, request ID, and citation provenance.

### Health

| Method | Path | Description |
| --- | --- | --- |
| `GET` | `/api/health` | Returns app, embedding, Ollama, model, and component diagnostics. |

## Environment Variables

| Variable | Default | Description |
| --- | --- | --- |
| `API_KEY` | unset | Optional shared bearer token for `/api/chat/*` and `/api/ingest/*`. |
| `VITE_API_KEY` | unset | Optional frontend bearer token for local protected development. |
| `EMBEDDING_PROVIDER` | `sentence_transformers` | `sentence_transformers`, `flagembedding`, or `ollama`. |
| `EMBEDDING_MODEL` | `BAAI/bge-small-en-v1.5` | Embedding model name. |
| `OLLAMA_BASE_URL` | `http://localhost:11434` | Ollama API base URL. |
| `LLM_MODEL` | `llama3.1:8b-instruct-q4_K_M` | Default Ollama generation model. |
| `TOP_K` | `3` | Final context chunks per query. |
| `MAX_SIMILARITY_DISTANCE` | `0.65` | Maximum dense retrieval distance before fallback logic. |
| `CHUNK_SIZE` | `1400` | Maximum chunk size. |
| `CHUNK_OVERLAP` | `280` | Chunk overlap. |
| `INGEST_BASE_DIR` | `backend/data/ingest` | Security boundary for path ingestion. |
| `ENABLE_HYDE` | `false` | Optional HyDE query transformation. |
| `ENABLE_MULTI_QUERY` | `false` | Optional generated query reformulations. |
| `ENABLE_PARENT_DOCUMENT_RETRIEVAL` | `false` | Optional parent-document context replacement. |
| `ENABLE_VLM_PDF_ASSIST` | `false` | Optional local vision-model PDF page assistance. |
| `CROSS_ENCODER_MODEL` | unset | Optional local reranker model. |

See `backend/app/config.py` for the complete settings list.

## Smoke Test

```powershell
cd backend
python scripts/smoke_e2e.py --workspace e2e-file-only-proof
```

If `API_KEY` is set, add `--api-key <token>`.

## Local Evaluation

Run the checked-in fixture benchmark:

```powershell
cd backend
python scripts/evaluate_rag.py --preset quick
```

Artifacts are written to `backend/data/eval_runs/<timestamp>/`:

- `results.json`
- `metrics.csv`
- `summary.md`

The quick benchmark ingests local fixture documents and compares dense, lexical, hybrid, and hybrid-with-compression retrieval. It reports Recall@k, MRR, nDCG@k, context precision/recall, citation precision, groundedness heuristic, ingest success, OCR marker rate, and query latency. It is useful for regression and academic evidence, not for state-of-the-art claims.

## Notes

- Vector data is persisted in `backend/data/chroma`.
- Uploaded files are saved temporarily to `backend/data/uploads/` and deleted after indexing.
- Path ingestion resolves only under `INGEST_BASE_DIR`.
- Structured citations include document ID, chunk ID, filename/source, page number when available, section title when inferred, snippet, retrieval rank, score, source type, OCR marker, and optional offsets.
- The frontend persists session, theme, workspace, model, and optional local token state in browser storage.
- API logs are structured and each request receives an `X-Request-ID` response header.
- No document content is sent to cloud services by the main code path.
