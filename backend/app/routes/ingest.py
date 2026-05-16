from __future__ import annotations

import asyncio
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Response, UploadFile
import httpx

from app.config import settings
from app.deps import get_rag_service, require_api_key
from app.schemas import (
    IngestDocument,
    IngestDocumentsResponse,
    IngestJobCreateResponse,
    IngestJobStatusResponse,
    IngestPathRequest,
    IngestResponse,
    IngestUrlRequest,
    IngestWorkspacesResponse,
    WorkspaceInfo,
)
from app.services.loader import SUPPORTED_EXTENSIONS
from app.services.rag import IngestFileRef, RAGService
from app.services.state_store import StateStore

router = APIRouter(prefix="/ingest", tags=["ingest"], dependencies=[Depends(require_api_key)])

INGEST_JOBS_LOCK = asyncio.Lock()
STATE_STORE = StateStore(settings.state_db_path)


async def _set_job_state(job_id: str, **updates: str | int | None) -> None:
    async with INGEST_JOBS_LOCK:
        await asyncio.to_thread(STATE_STORE.update_ingest_job, job_id, **updates)


async def _run_ingest_job(
    job_id: str,
    file_refs: list[IngestFileRef],
    workspace_id: str | None,
) -> None:
    await _set_job_state(job_id, status="running")

    try:
        rag_service = await asyncio.to_thread(get_rag_service)

        async def _progress(stats: object) -> None:
            await _set_job_state(
                job_id,
                files_processed=int(getattr(stats, "files_processed", 0)),
                chunks_indexed=int(getattr(stats, "chunks_indexed", 0)),
                skipped_files=int(getattr(stats, "skipped_files", 0)),
            )

        stats = await rag_service.ingest_uploaded_files_with_progress(file_refs, _progress, workspace_id)
        for file_ref in file_refs:
            file_ref.path.unlink(missing_ok=True)
        await _set_job_state(
            job_id,
            status="completed",
            files_processed=stats.files_processed,
            chunks_indexed=stats.chunks_indexed,
            skipped_files=stats.skipped_files,
            error=None,
        )
    except Exception as exc:
        await _set_job_state(job_id, status="failed", error=str(exc))


@router.post("/path", response_model=IngestResponse)
async def ingest_path(
    payload: IngestPathRequest,
    rag_service: RAGService = Depends(get_rag_service),
) -> IngestResponse:
    try:
        stats = await rag_service.ingest_path(payload.path, payload.workspace_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc

    return IngestResponse(**stats.__dict__)


@router.post("/url", response_model=IngestResponse)
async def ingest_url(
    payload: IngestUrlRequest,
    rag_service: RAGService = Depends(get_rag_service),
) -> IngestResponse:
    try:
        stats = await rag_service.ingest_url(payload.url, payload.workspace_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"Failed to fetch URL: {exc}") from exc

    return IngestResponse(**stats.__dict__)


@router.get("/documents", response_model=IngestDocumentsResponse)
async def list_documents(
    workspace_id: str | None = Query(default=None),
    rag_service: RAGService = Depends(get_rag_service),
) -> IngestDocumentsResponse:
    docs = await asyncio.to_thread(rag_service.list_documents, workspace_id)
    return IngestDocumentsResponse(documents=[IngestDocument(**doc) for doc in docs])


@router.get("/workspaces", response_model=IngestWorkspacesResponse)
async def list_workspaces(rag_service: RAGService = Depends(get_rag_service)) -> IngestWorkspacesResponse:
    workspaces = await asyncio.to_thread(rag_service.list_workspaces)
    return IngestWorkspacesResponse(workspaces=[WorkspaceInfo(workspace_id=workspace) for workspace in workspaces])


@router.delete("/documents/{doc_id}", status_code=204, response_class=Response)
async def delete_document(
    doc_id: str,
    workspace_id: str | None = Query(default=None),
    rag_service: RAGService = Depends(get_rag_service),
) -> Response:
    await asyncio.to_thread(rag_service.delete_document, doc_id, workspace_id)
    return Response(status_code=204)


@router.delete("/documents", status_code=204, response_class=Response)
async def clear_documents(
    workspace_id: str | None = Query(default=None),
    rag_service: RAGService = Depends(get_rag_service),
) -> Response:
    await asyncio.to_thread(rag_service.clear_documents, workspace_id)
    return Response(status_code=204)


@router.post("/files", response_model=IngestJobCreateResponse, status_code=202)
async def ingest_files(
    files: list[UploadFile] = File(...),
    workspace_id: str | None = Form(default=None),
) -> IngestJobCreateResponse:
    if not files:
        raise HTTPException(status_code=400, detail="No files uploaded")

    upload_dir = settings.data_dir / "uploads"
    upload_dir.mkdir(parents=True, exist_ok=True)

    unsupported_files = [
        (file.filename or "<unnamed>")
        for file in files
        if Path(file.filename or "").suffix.lower() not in SUPPORTED_EXTENSIONS
    ]
    if unsupported_files:
        raise HTTPException(
            status_code=400,
            detail=(
                "Unsupported file type(s): "
                + ", ".join(unsupported_files)
                + ". Supported types: "
                + ", ".join(sorted(SUPPORTED_EXTENSIONS))
            ),
        )

    persisted_files: list[IngestFileRef] = []
    for file in files:
        original_name = Path(file.filename or "").name or "<unnamed>"
        suffix = Path(original_name).suffix.lower()
        target_path = upload_dir / f"{uuid4()}{suffix}"
        content = await file.read()
        max_bytes = settings.max_file_size_mb * 1024 * 1024
        if len(content) > max_bytes:
            for persisted_file in persisted_files:
                persisted_file.path.unlink(missing_ok=True)
            raise HTTPException(
                status_code=413,
                detail=f"File too large: {original_name}. Maximum size is {settings.max_file_size_mb} MB",
            )
        target_path.write_bytes(content)
        persisted_files.append(IngestFileRef(path=target_path, display_name=original_name))

    job_id = str(uuid4())
    async with INGEST_JOBS_LOCK:
        await asyncio.to_thread(STATE_STORE.create_ingest_job, job_id, len(persisted_files))

    asyncio.create_task(_run_ingest_job(job_id, persisted_files, workspace_id))
    return IngestJobCreateResponse(job_id=job_id, status="queued")


@router.get("/jobs/{job_id}", response_model=IngestJobStatusResponse)
async def get_ingest_job_status(job_id: str) -> IngestJobStatusResponse:
    async with INGEST_JOBS_LOCK:
        job = await asyncio.to_thread(STATE_STORE.get_ingest_job, job_id)

    if not job:
        raise HTTPException(status_code=404, detail=f"Ingest job not found: {job_id}")

    return IngestJobStatusResponse(
        job_id=job_id,
        status=str(job.get("status", "unknown")),
        files_total=int(job.get("files_total", 0)),
        files_processed=int(job.get("files_processed", 0)),
        chunks_indexed=int(job.get("chunks_indexed", 0)),
        skipped_files=int(job.get("skipped_files", 0)),
        error=job.get("error") if isinstance(job.get("error"), str) or job.get("error") is None else str(job.get("error")),
    )
