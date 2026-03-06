from __future__ import annotations

import asyncio
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile

from app.config import settings
from app.deps import get_rag_service
from app.schemas import IngestJobCreateResponse, IngestJobStatusResponse, IngestPathRequest, IngestResponse
from app.services.loader import SUPPORTED_EXTENSIONS
from app.services.rag import RAGService

router = APIRouter(prefix="/ingest", tags=["ingest"])

INGEST_JOBS: dict[str, dict[str, str | int | None]] = {}
INGEST_JOBS_LOCK = asyncio.Lock()


async def _set_job_state(job_id: str, **updates: str | int | None) -> None:
    async with INGEST_JOBS_LOCK:
        job = INGEST_JOBS.get(job_id)
        if not job:
            return
        for key, value in updates.items():
            job[key] = value


async def _run_ingest_job(job_id: str, file_paths: list[Path], rag_service: RAGService) -> None:
    await _set_job_state(job_id, status="running")

    try:
        async def _progress(stats: object) -> None:
            await _set_job_state(
                job_id,
                files_processed=int(getattr(stats, "files_processed", 0)),
                chunks_indexed=int(getattr(stats, "chunks_indexed", 0)),
                skipped_files=int(getattr(stats, "skipped_files", 0)),
            )

        stats = await rag_service.ingest_uploaded_files_with_progress(file_paths, _progress)
        for file_path in file_paths:
            file_path.unlink(missing_ok=True)
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
        stats = await rag_service.ingest_path(payload.path)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc

    return IngestResponse(**stats.__dict__)


@router.post("/files", response_model=IngestJobCreateResponse, status_code=202)
async def ingest_files(
    files: list[UploadFile] = File(...),
    rag_service: RAGService = Depends(get_rag_service),
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

    persisted_paths: list[Path] = []
    for file in files:
        suffix = Path(file.filename or "").suffix.lower()
        target_path = upload_dir / f"{uuid4()}{suffix}"
        content = await file.read()
        target_path.write_bytes(content)
        persisted_paths.append(target_path)

    job_id = str(uuid4())
    async with INGEST_JOBS_LOCK:
        INGEST_JOBS[job_id] = {
            "status": "queued",
            "files_total": len(persisted_paths),
            "files_processed": 0,
            "chunks_indexed": 0,
            "skipped_files": 0,
            "error": None,
        }

    asyncio.create_task(_run_ingest_job(job_id, persisted_paths, rag_service))
    return IngestJobCreateResponse(job_id=job_id, status="queued")


@router.get("/jobs/{job_id}", response_model=IngestJobStatusResponse)
async def get_ingest_job_status(job_id: str) -> IngestJobStatusResponse:
    async with INGEST_JOBS_LOCK:
        job = INGEST_JOBS.get(job_id)

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
