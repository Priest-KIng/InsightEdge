# InsightEdge

InsightEdge is a privacy-first local RAG system: ingest local files, embed and index them locally, and answer questions with a local LLM.

## Architecture

1. **Document ingestion** — supports `.txt`, `.md`, `.pdf`, `.docx`, `.csv`, `.xlsx`, `.html`, `.epub`, `.pptx`; PDFs use `pdfplumber` for text and table extraction with `pytesseract`/`pdf2image` as OCR fallback for scanned pages
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
ollama pull phi3:mini
ollama serve
```

## OCR dependencies for PDF fallback

InsightEdge's scanned-PDF OCR path requires both **Tesseract OCR** and **Poppler** (used by `pdf2image`).

### Windows

Install with Chocolatey:

```powershell
choco install tesseract -y
choco install poppler -y
```

If Chocolatey is unavailable, install Tesseract and Poppler manually and ensure both `tesseract.exe` and Poppler's `bin` folder are on `PATH`.

### macOS

Install with Homebrew:

```bash
brew install tesseract poppler
```

### Linux (Debian/Ubuntu)

```bash
sudo apt-get update
sudo apt-get install -y tesseract-ocr poppler-utils
```

Without these dependencies, OCR fallback for scanned PDF pages and embedded PDF images may return empty output.

## API summary

### Ingest

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/ingest/files` | Upload one or more files (multipart `files`); returns `{"job_id": "...", "status": "queued"}` |
| `GET`  | `/api/ingest/jobs/{job_id}` | Poll async ingest job status (`queued` → `running` → `completed`/`failed`) |
| `POST` | `/api/ingest/path` | Ingest a server-side path: `{"path": "relative/or/absolute/path"}` |
| `POST` | `/api/ingest/url` | Ingest a web page URL: `{"url": "https://..."}` |

### Chat

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/chat` | Ask a question: `{"question": "...", "session_id": "...", "llm_model": "...", "history": [...]}` |
| `GET`  | `/api/chat/session/{session_id}` | Retrieve conversation history for a session |
| `DELETE` | `/api/chat/session/{session_id}` | Clear conversation history for a session |

### Health

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/health` | Returns app + component diagnostics (`embedding`, `ollama`) with overall `status` of `ok` or `degraded` |

## Environment variables

All variables are optional; defaults are listed below.

| Variable | Default | Description |
|----------|---------|-------------|
| `APP_NAME` | `InsightEdge` | Application name shown in API metadata |
| `APP_ENV` | `dev` | Runtime environment label |
| `API_KEY` | *(unset)* | Optional shared bearer token required for `/api/chat/*` and `/api/ingest/*` when set |
| `EMBEDDING_PROVIDER` | `sentence_transformers` | `sentence_transformers`, `flagembedding`, or `ollama` |
| `EMBEDDING_MODEL` | `BAAI/bge-small-en-v1.5` | Embedding model name for the selected provider (e.g. `BAAI/bge-m3`, `nomic-embed-text`) |
| `OLLAMA_BASE_URL` | `http://localhost:11434` | Ollama API base URL |
| `LLM_MODEL` | `phi3:mini` | Ollama model name (lightweight default for low-VRAM GPUs) |
| `LLM_TIMEOUT_SECONDS` | `180` | Timeout for Ollama generation requests in seconds |
| `TOP_K` | `3` | Number of chunks retrieved per query |
| `MAX_SIMILARITY_DISTANCE` | `0.65` | Maximum Chroma L2 distance; results above this threshold are discarded |
| `ENABLE_HYDE` | `false` | Enables HyDE query transformation before vector retrieval |
| `HYDE_MAX_CHARS` | `1500` | Maximum characters kept from the generated hypothetical answer |
| `ENABLE_MULTI_QUERY` | `false` | Enables LLM-generated query reformulations before retrieval |
| `MULTI_QUERY_COUNT` | `3` | Number of extra query variants generated when multi-query is enabled |
| `ENABLE_PARENT_DOCUMENT_RETRIEVAL` | `false` | Replaces retrieved child chunks with stored parent-document context |
| `PARENT_DOCUMENT_MAX_CHARS` | `4000` | Maximum characters persisted for parent-document context |
| `ENABLE_SELF_RAG` | `false` | Enables one or more iterative follow-up retrieval passes when context is insufficient |
| `SELF_RAG_MAX_FOLLOWUPS` | `1` | Maximum iterative follow-up retrieval passes when self-RAG is enabled |
| `ENABLE_VLM_PDF_ASSIST` | `false` | Renders PDF page images during ingest and adds optional VLM context at answer time |
| `VLM_MODEL` | `minicpm-v` | Ollama vision-capable model used for PDF image context |
| `VLM_MAX_PAGES` | `2` | Maximum rendered pages used for VLM context |
| `VLM_IMAGE_DPI` | `180` | Rendering DPI for stored PDF page images |
| `CHUNK_SIZE` | `1400` | Maximum characters per chunk |
| `CHUNK_OVERLAP` | `280` | Character overlap between adjacent chunks |
| `MAX_FILE_SIZE_MB` | `25` | Files larger than this are skipped during ingest |
| `INGEST_BASE_DIR` | `backend/data/ingest` | Security boundary for `POST /api/ingest/path` |
| `CORS_ORIGINS` | `http://localhost:5173` | Comma-separated allowed CORS origins |
| `CORS_ALLOW_CREDENTIALS` | `false` | Whether to allow credentials in CORS requests |

## Embedding Experiments

Run the quick embedding smoke-test:

```powershell
cd backend
python scripts/evaluate_embeddings.py --provider sentence_transformers --model BAAI/bge-small-en-v1.5
```

Examples for checklist models:

```powershell
# BGE large (higher quality, higher RAM)
python scripts/evaluate_embeddings.py --provider sentence_transformers --model BAAI/bge-large-en-v1.5

# BGE-M3 via FlagEmbedding
python scripts/evaluate_embeddings.py --provider flagembedding --model BAAI/bge-m3

# Ollama embedding models
python scripts/evaluate_embeddings.py --provider ollama --model nomic-embed-text
python scripts/evaluate_embeddings.py --provider ollama --model mxbai-embed-large
```

## LLM Experiments

Quick latency smoke-test for an Ollama model:

```powershell
cd backend
python scripts/evaluate_llm_models.py --model phi3:mini
```

Checklist model examples:

```powershell
python scripts/evaluate_llm_models.py --model llama3.1:70b-instruct-q4_K_M
python scripts/evaluate_llm_models.py --model phi4:14b
python scripts/evaluate_llm_models.py --model qwen2.5:14b
python scripts/evaluate_llm_models.py --model mistral-small3.1
```

## Vision Assist For PDFs

For image-heavy/scanned PDFs, enable optional VLM augmentation:

```powershell
# backend/.env
ENABLE_VLM_PDF_ASSIST=true
VLM_MODEL=minicpm-v
VLM_MAX_PAGES=2
```

When enabled, InsightEdge stores rendered PDF page images during ingest and uses a vision model to add extra context at answer time.

## Notes

- Vector data is persisted in `backend/data/chroma` (ChromaDB SQLite + segment files)
- Uploaded files are saved temporarily to `backend/data/uploads/` and deleted after indexing
- `POST /api/ingest/path` only ingests paths that resolve within `INGEST_BASE_DIR`
- Chunking is sentence-aware: text is split on `.`, `!`, `?` boundaries before applying size limits
- PDF loading uses `pdfplumber` for text/table extraction; scanned pages fall back to `pytesseract` OCR via `pdf2image`
- Chat sessions and ingest jobs are persisted in `backend/data/state.db` (SQLite)
- The frontend persists its `session_id` in `localStorage` under the key `insightedge_chat_session_id`
- API logs are emitted as structured JSON and each request receives an `X-Request-ID` response header
- Defaults are tuned for low-resource machines (e.g., 4 GB VRAM): lightweight LLM model and advanced retrieval toggles disabled unless enabled via env
- No document content is sent to cloud services by this codebase
