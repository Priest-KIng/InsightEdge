# InsightEdge Setup and Operations Guide

This guide starts InsightEdge from a fresh clone on Windows, macOS, or Linux. InsightEdge is a local RAG application: documents, embeddings, vector data, chat history, and generated answers stay on the machine running the project unless you configure a remote service yourself.

## What Runs

InsightEdge has three local processes or services:

1. Ollama serves the local language model on `http://localhost:11434`.
2. The FastAPI backend serves the API on `http://localhost:8000`.
3. The React/Vite frontend serves the browser UI on `http://localhost:5173`.

The backend also downloads the configured embedding model on first use. That model is cached locally by the embedding library. The first startup therefore needs internet access and enough disk space; later runs can use the cache.

## Requirements

Install these before cloning or starting the application:

- Git.
- Python 3.11. Python 3.10 or newer is required by the type syntax used in the backend; Python 3.11 is the tested version.
- Node.js 20.19+ or Node.js 22.12+. These versions are compatible with the Vite version in this repository. npm is included with Node.js.
- Ollama. Use the official installer at <https://ollama.com/download>.
- At least 8 GB of system memory is recommended for the default embedding and language models. More memory improves PDF processing and larger Ollama models.
- A GPU is optional. Ollama can run on CPU, but generation will be slower.

For scanned PDF OCR, install these additional native tools:

- Tesseract OCR.
- Poppler, including the `pdftoppm` or equivalent utilities.

OCR is optional for text-based files and text-based PDFs.

## Clone the Repository

```bash
git clone https://github.com/Priest-KIng/InsightEdge.git
cd InsightEdge
```

The important directories are:

```text
backend/                 FastAPI API, ingestion, retrieval, tests
backend/eval/            Small checked-in evaluation corpus
docs/                    Setup and evaluation notes
frontend/                React/Vite browser application
.env.example             Backend configuration template
frontend/.env.example    Frontend configuration template
```

Do not commit `.env` files, `backend/data/`, `frontend/node_modules/`, or `frontend/dist/`. They are local runtime or build output and are ignored by Git.

## Configure the Environment

The backend reads configuration from `backend/.env` first and then the repository-root `.env`. The frontend reads `frontend/.env` at build or dev-server startup.

### Windows PowerShell

```powershell
Copy-Item .env.example .env
Copy-Item frontend\.env.example frontend\.env
```

### macOS or Linux

```bash
cp .env.example .env
cp frontend/.env.example frontend/.env
```

The checked-in examples are ready for the default local ports and `phi3:mini`. You only need to edit them when changing ports, models, storage locations, CORS, or optional features.

`API_KEY` is optional and empty by default for local development. If you set it, use the same value as `VITE_API_KEY` or enter the value in the frontend's Local API Token field. Never put a real password, cloud token, or private key into a committed example file.

## Install the Backend

### Windows PowerShell

```powershell
cd backend
py -3.11 -m venv .venv
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
cd ..
```

If `py -3.11` is unavailable, install Python 3.11 and ensure the Python launcher is on PATH.

### macOS or Linux

```bash
cd backend
python3.11 -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
cd ..
```

Keep the virtual environment activated in any terminal used to run backend commands. The backend dependencies include FastAPI, ChromaDB, sentence-transformers, document loaders, OCR bindings, and pytest.

## Install the Frontend

Open a second terminal at the repository root:

```bash
cd frontend
npm install
```

The committed `package-lock.json` makes this installation repeatable. `npm ci` can be used instead of `npm install` for a clean CI-style install.

## Install and Run Ollama

Install Ollama from <https://ollama.com/download>.

### Windows

Download and run the Windows installer. Ollama normally runs in the background after installation. In PowerShell, verify it:

```powershell
ollama --version
```

If the command is not available, restart the terminal after installing Ollama. The official Windows notes are at <https://docs.ollama.com/windows>.

### macOS

Install the Ollama application from the official download page, launch it once, then verify:

```bash
ollama --version
```

### Linux

```bash
curl -fsSL https://ollama.com/install.sh | sh
ollama serve
```

Leave `ollama serve` running in its terminal, or install Ollama as a system service using the official Linux instructions at <https://docs.ollama.com/linux>.

### Download the models

The default configuration uses `phi3:mini`, which is a practical starting point for a small local machine:

```bash
ollama pull phi3:mini
ollama ls
ollama run phi3:mini "Say hello in one sentence."
```

The Ollama API should answer at `http://localhost:11434`. On Windows PowerShell:

```powershell
Invoke-RestMethod http://localhost:11434/api/tags
```

On macOS or Linux:

```bash
curl http://localhost:11434/api/tags
```

InsightEdge checks that `LLM_MODEL` is installed. If it is not installed, `/api/health` reports a degraded Ollama component and chat requests cannot use that model. To use another installed model, set `LLM_MODEL` and usually `ROUTER_SIMPLE_MODEL` and `ROUTER_BALANCED_MODEL` to the same model in `.env`, then restart the backend.

The optional strong model defaults to `llama3.1:8b-instruct-q4_K_M`. It is not required for the application to start and can use several gigabytes of disk and memory. Install it only when the machine can handle it:

```bash
ollama pull llama3.1:8b-instruct-q4_K_M
```

Ollama model management commands are documented at <https://docs.ollama.com/cli>.

## Install OCR Tools

### Windows with Chocolatey

```powershell
choco install tesseract -y
choco install poppler -y
```

If the executables are not found after installation, restart the terminal or add their installation directories to PATH.

### macOS with Homebrew

```bash
brew install tesseract poppler
```

### Debian or Ubuntu

```bash
sudo apt-get update
sudo apt-get install -y tesseract-ocr poppler-utils
```

When OCR is unavailable, normal text extraction still works. Scanned pages may be skipped or contain no text, and the backend logs the extraction problem.

## Start the Application

Start Ollama first, either from its desktop application or with `ollama serve`.

### Terminal 1: backend

Windows PowerShell:

```powershell
cd backend
.\.venv\Scripts\Activate.ps1
python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

macOS or Linux:

```bash
cd backend
. .venv/bin/activate
python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

The first backend initialization may take time while the embedding model is downloaded and loaded. The API is available at `http://localhost:8000` and interactive FastAPI documentation is available at `http://localhost:8000/docs`.

### Terminal 2: frontend

```bash
cd frontend
npm run dev
```

Open <http://localhost:5173> in a browser.

### Verify the backend

Open <http://localhost:8000/api/health>, or run:

```bash
curl http://localhost:8000/api/health
```

The response includes embedding and Ollama component status. `status: "ok"` means both are ready. `status: "degraded"` usually means the embedding model is still loading, Ollama is not running, or `LLM_MODEL` is not installed.

## Use the Browser UI

1. Open the frontend at <http://localhost:5173>.
2. Leave the workspace as `default`, or create a new workspace name such as `research`.
3. Select one or more supported files and choose `Upload & Process`.
4. Wait for the ingest status to become completed. The document list shows indexed files and chunk counts.
5. Ask a question in the chat area. Responses stream from Ollama and include structured citations when evidence is retrieved.
6. Use the workspace selector to keep separate document collections and chat sessions isolated.
7. Delete one document from the document list, or use `Clear` to remove every document in the active workspace.
8. Use the export controls in the chat area when a local Markdown, JSON, or text copy is needed.

Supported upload extensions are `.txt`, `.md`, `.pdf`, `.docx`, `.csv`, `.xlsx`, `.html`, `.htm`, `.epub`, and `.pptx`. Uploads are limited to `MAX_FILE_SIZE_MB` per file, defaulting to 25 MB.

The application does not fetch URLs or web pages. It processes local files supplied through the browser or through the server-side path endpoint.

## API Usage Without the Frontend

The default API base is `http://localhost:8000/api`.

Upload a file with curl:

```bash
curl -X POST http://localhost:8000/api/ingest/files \
  -F "workspace_id=research" \
  -F "files=@/absolute/path/to/document.pdf"
```

On Windows, use `curl.exe` and a Windows path:

```powershell
curl.exe -X POST http://localhost:8000/api/ingest/files `
  -F "workspace_id=research" `
  -F "files=@C:\path\to\document.pdf"
```

The upload returns a `job_id`. Poll it until the status is `completed`:

```bash
curl http://localhost:8000/api/ingest/jobs/<job_id>
```

List documents in a workspace:

```bash
curl "http://localhost:8000/api/ingest/documents?workspace_id=research"
```

Ask a question:

```bash
curl -X POST http://localhost:8000/api/chat \
  -H "Content-Type: application/json" \
  -d '{"question":"Summarize the document.","workspace_id":"research"}'
```

For browser-style streaming, use `POST /api/chat/stream`; it returns Server-Sent Events containing token events followed by a final event with the answer and citations. The full endpoint list is in the FastAPI docs at <http://localhost:8000/docs>.

To ingest a server-side directory, place files below `backend/data/ingest` or the directory configured by `INGEST_BASE_DIR`, then call:

```bash
curl -X POST http://localhost:8000/api/ingest/path \
  -H "Content-Type: application/json" \
  -d '{"path":"backend/data/ingest","workspace_id":"research"}'
```

Path ingestion rejects paths outside `INGEST_BASE_DIR`.

## Environment Reference

All settings are optional. Defaults are defined in `backend/app/config.py` and are also shown in `.env.example`.

| Variable | Default | Purpose |
| --- | --- | --- |
| `API_KEY` | empty | Optional bearer token required by chat and ingestion routes. |
| `DEFAULT_WORKSPACE_ID` | `default` | Workspace used when a request does not specify one. |
| `EMBEDDING_PROVIDER` | `sentence_transformers` | Embedding backend: `sentence_transformers`, `flagembedding`, or `ollama`. |
| `EMBEDDING_MODEL` | `BAAI/bge-small-en-v1.5` | Local embedding model. |
| `OLLAMA_BASE_URL` | `http://localhost:11434` | Ollama server address. |
| `LLM_MODEL` | `phi3:mini` | Default generation model; it must be installed in Ollama. |
| `LLM_CONTEXT_LENGTH` | `4096` | Ollama context window. Larger values use more memory. |
| `LLM_MAX_OUTPUT_TOKENS` | `384` | Maximum generated output length. |
| `LLM_NUM_GPU` | `-1` | Ollama GPU layer setting; `0` forces CPU. |
| `ROUTER_SIMPLE_MODEL` | `phi3:mini` | Model tier for simple questions. |
| `ROUTER_BALANCED_MODEL` | `phi3:mini` | Model tier for medium questions. |
| `ROUTER_STRONG_MODEL` | `llama3.1:8b-instruct-q4_K_M` | Optional model tier for difficult synthesis. |
| `ROUTER_STRONG_NUM_GPU` | `0` | GPU layers for the strong tier. |
| `ENABLE_RETRIEVAL_ROUTER` | `true` | Enables deterministic query-to-retrieval routing. |
| `ENABLE_MODEL_ROUTER` | `true` | Enables model selection by query complexity. |
| `TOP_K` | `3` | Number of final evidence chunks. |
| `MAX_SIMILARITY_DISTANCE` | `0.65` | Dense retrieval distance cutoff. |
| `CHUNK_SIZE` | `1400` | Target chunk size in characters. |
| `CHUNK_OVERLAP` | `280` | Chunk overlap in characters. |
| `MAX_FILE_SIZE_MB` | `25` | Maximum upload size per file. |
| `INGEST_BASE_DIR` | `backend/data/ingest` | Allowed root for server-side path ingestion. |
| `DATA_DIR` | `backend/data` | Runtime data directory for SQLite, uploads, and evaluation output. |
| `VECTOR_DB_DIR` | `backend/data/chroma` | Persistent ChromaDB directory. |
| `CORS_ORIGINS` | localhost frontend URLs | JSON list of allowed browser origins. |
| `CORS_ALLOW_CREDENTIALS` | `false` | Whether browser credentials are allowed by CORS. |

Advanced retrieval, OCR/VLM, reranking, compression, and worker settings are included in `.env.example`. Restart the backend after changing any backend setting. Restart the Vite dev server after changing any `VITE_` setting.

## API Key Protection

For local development, leave `API_KEY` empty. To enable the optional shared bearer token:

```text
API_KEY=replace-with-a-local-random-token
```

Then either set the same value in `frontend/.env` as `VITE_API_KEY`, or start the frontend with an empty `VITE_API_KEY` and enter the token in the Local API Token field. Restart both processes after changing env files. Send the token to direct API calls as:

```bash
curl http://localhost:8000/api/ingest/documents \
  -H "Authorization: Bearer replace-with-a-local-random-token"
```

Do not expose a real production credential in GitHub. The example values in this repository are placeholders and local defaults only.

## Tests and Evaluation

Run backend tests from the repository root:

Windows PowerShell:

```powershell
cd backend
.\.venv\Scripts\Activate.ps1
python -m pytest
python -m compileall -q app scripts
cd ..
```

macOS or Linux:

```bash
cd backend
. .venv/bin/activate
python -m pytest
python -m compileall -q app scripts
cd ..
```

Build the frontend:

```bash
cd frontend
npm run build
```

Run the local end-to-end upload and retrieval check while the backend and Ollama are running:

```bash
cd backend
python scripts/smoke_e2e.py --workspace e2e-file-only-proof
```

Add `--api-key <token>` when API key protection is enabled. Add `--skip-chat` to verify only health, upload, ingestion, and document listing. The smoke test creates a small temporary workspace and leaves its indexed document in that workspace; delete the workspace from the UI afterward if needed.

Run the checked-in local benchmark:

```bash
cd backend
python scripts/evaluate_rag.py
```

Evaluation artifacts are written under ignored runtime data at `backend/data/eval_runs/<timestamp>/`. See [evaluation.md](evaluation.md) for metric definitions and limitations.

## Runtime Data and Resetting Local State

The backend creates these directories and files automatically:

- `backend/data/chroma/`: vector database.
- `backend/data/state.db`: SQLite chat sessions and ingest jobs.
- `backend/data/uploads/`: temporary upload files, normally removed after processing.
- `backend/data/eval_runs/`: benchmark outputs.
- `backend/data/vlm_pages/`: optional temporary VLM PDF images.

To reset all local indexed data, stop the backend and remove `backend/data/`. It will be recreated on the next start. This permanently removes local documents, vectors, chat sessions, and evaluation outputs. Prefer the UI's document and workspace deletion controls when only part of the data should be removed.

## Troubleshooting

### `/api/health` reports Ollama as degraded

Check that Ollama is running and reachable at the configured `OLLAMA_BASE_URL`:

```bash
ollama ls
curl http://localhost:11434/api/tags
```

Confirm the exact model name in `.env` matches the output of `ollama ls`, then restart the backend.

### Chat returns an error but ingestion works

The embedding model and Ollama generation model are separate. Confirm the Ollama model is installed with `ollama pull phi3:mini`. If the model is running on CPU, allow more time for generation or lower `LLM_MAX_OUTPUT_TOKENS`.

### The embedding model takes a long time to start

The first startup downloads `BAAI/bge-small-en-v1.5` and initializes ChromaDB. Keep the backend terminal open and wait for the health endpoint to respond. A later startup should reuse the local model cache.

### The browser cannot reach the backend

Confirm both processes are running, open `http://localhost:5173`, and check that `frontend/.env` contains `VITE_API_BASE_URL=http://localhost:8000/api`. If the frontend uses another origin or port, add it to `CORS_ORIGINS` in the backend `.env` and restart the backend.

### A PDF has no useful text

Text PDFs use `pdfplumber`; scanned PDFs need Tesseract and Poppler. Install both tools, verify they are on PATH, and re-upload the PDF. Existing indexed chunks are not automatically rebuilt, so delete the old document and ingest it again.

### Port 8000 or 5173 is already in use

Start the backend on another port, for example `--port 8001`, then set `VITE_API_BASE_URL=http://localhost:8001/api` and restart the frontend. The Vite port is configured in `frontend/vite.config.js` and can be changed there.

### API key requests return 401

Use the exact same token in backend `API_KEY` and frontend `VITE_API_KEY`, or enter it in the UI. Include the header `Authorization: Bearer <token>` in direct API requests.

## Privacy and Security Notes

- The main application path is local-only and does not fetch URLs.
- Documents are sent to the local embedding process and local Ollama service configured by `OLLAMA_BASE_URL`.
- Keep `.env` files private when they contain API keys or non-public infrastructure URLs.
- The optional `API_KEY` is a shared local bearer token, not a full user-management system.
- Do not expose the development server directly to the public internet without adding proper authentication, TLS, rate limiting, and deployment hardening.
