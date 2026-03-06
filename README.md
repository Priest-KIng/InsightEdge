# InsightEdge

InsightEdge is a privacy-first local RAG system: ingest local files, embed and index them locally, and answer questions with a local LLM.

## Architecture

1. **Document ingestion** — supports `.txt`, `.md`, `.pdf`, `.docx`; PDFs use `pdfplumber` for text and table extraction with `pytesseract`/`pdf2image` as OCR fallback for scanned pages
2. **Sentence-aware chunking** — splits on sentence boundaries (default `CHUNK_SIZE=1400`, `CHUNK_OVERLAP=280`)
3. **Embeddings** — `BAAI/bge-small-en-v1.5` via `sentence-transformers`
4. **Vector search** — persistent `ChromaDB` with similarity-distance filtering (`MAX_SIMILARITY_DISTANCE=0.65`)
5. **LLM generation** — local model via `Ollama` (default `llama3.1:8b-instruct-q4_K_M`)
6. **React frontend** — file upload, async ingest-job polling, multi-turn chat with session history, source citations, dark/light theme

## Backend setup

```powershell
cd backend
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

> Copy and edit a `.env` file in `backend/` (or the project root) to override any defaults listed below.

## Frontend setup

```powershell
cd frontend
npm install
npm run dev
```

The frontend runs on `http://localhost:5173` by default. Optionally set `VITE_API_BASE_URL` in `frontend/.env` to point at a non-default backend address.

## Ollama setup

```powershell
ollama pull llama3.1:8b-instruct-q4_K_M
ollama serve
```

## API summary

### Ingest

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/ingest/files` | Upload one or more files (multipart `files`); returns `{"job_id": "...", "status": "queued"}` |
| `GET`  | `/api/ingest/jobs/{job_id}` | Poll async ingest job status (`queued` → `running` → `completed`/`failed`) |
| `POST` | `/api/ingest/path` | Ingest a server-side path: `{"path": "relative/or/absolute/path"}` |

### Chat

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/chat` | Ask a question: `{"question": "...", "session_id": "...", "history": [...]}` |
| `GET`  | `/api/chat/session/{session_id}` | Retrieve conversation history for a session |
| `DELETE` | `/api/chat/session/{session_id}` | Clear conversation history for a session |

### Health

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/health` | Returns `{"status": "ok", "app": "InsightEdge"}` |

## Environment variables

All variables are optional; defaults are listed below.

| Variable | Default | Description |
|----------|---------|-------------|
| `APP_NAME` | `InsightEdge` | Application name shown in API metadata |
| `APP_ENV` | `dev` | Runtime environment label |
| `EMBEDDING_MODEL` | `BAAI/bge-small-en-v1.5` | HuggingFace sentence-transformer model |
| `OLLAMA_BASE_URL` | `http://localhost:11434` | Ollama API base URL |
| `LLM_MODEL` | `llama3.1:8b-instruct-q4_K_M` | Ollama model name |
| `TOP_K` | `4` | Number of chunks retrieved per query |
| `MAX_SIMILARITY_DISTANCE` | `0.65` | Maximum Chroma L2 distance; results above this threshold are discarded |
| `CHUNK_SIZE` | `1400` | Maximum characters per chunk |
| `CHUNK_OVERLAP` | `280` | Character overlap between adjacent chunks |
| `MAX_FILE_SIZE_MB` | `25` | Files larger than this are skipped during ingest |
| `INGEST_BASE_DIR` | `backend/data/ingest` | Security boundary for `POST /api/ingest/path` |
| `CORS_ORIGINS` | `http://localhost:5173` | Comma-separated allowed CORS origins |
| `CORS_ALLOW_CREDENTIALS` | `false` | Whether to allow credentials in CORS requests |

## Notes

- Vector data is persisted in `backend/data/chroma` (ChromaDB SQLite + segment files)
- Uploaded files are saved temporarily to `backend/data/uploads/` and deleted after indexing
- `POST /api/ingest/path` only ingests paths that resolve within `INGEST_BASE_DIR`
- Chunking is sentence-aware: text is split on `.`, `!`, `?` boundaries before applying size limits
- PDF loading uses `pdfplumber` for text/table extraction; scanned pages fall back to `pytesseract` OCR via `pdf2image`
- Chat sessions are stored in-memory (process-lifetime); clearing or restarting the server resets history
- The frontend persists its `session_id` in `localStorage` under the key `insightedge_chat_session_id`
- No document content is sent to cloud services by this codebase
