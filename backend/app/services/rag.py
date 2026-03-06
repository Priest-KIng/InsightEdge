from __future__ import annotations

import asyncio
from dataclasses import dataclass
import hashlib
import logging
from pathlib import Path
from typing import Awaitable, Callable

from app.config import settings
from app.schemas import ChatTurn, Citation
from app.services.chunker import chunk_text
from app.services.embeddings import EmbeddingService
from app.services.llm import LocalLLMService
from app.services.loader import DocumentLoadError, iter_supported_files, load_text
from app.services.vector_store import VectorStore

logger = logging.getLogger(__name__)


@dataclass
class IngestStats:
    files_processed: int = 0
    chunks_indexed: int = 0
    skipped_files: int = 0


class RAGService:
    def __init__(self) -> None:
        self.embedder = EmbeddingService(settings.embedding_model)
        self.vectordb = VectorStore(str(settings.vector_db_dir), settings.collection_name)
        self.llm = LocalLLMService(
            settings.ollama_base_url,
            settings.llm_model,
            timeout_seconds=settings.llm_timeout_seconds,
        )

    async def ingest_path(self, raw_path: str) -> IngestStats:
        base_dir = settings.ingest_base_dir.resolve()
        requested = Path(raw_path).expanduser()
        candidate = requested if requested.is_absolute() else (base_dir / requested)
        candidate = candidate.resolve()

        if not candidate.exists():
            raise FileNotFoundError(f"Path does not exist: {candidate}")

        if not candidate.is_relative_to(base_dir):
            raise PermissionError(f"Path must be under ingest base directory: {base_dir}")

        return await asyncio.to_thread(self._ingest_files, iter_supported_files(candidate))

    async def ingest_uploaded_files(self, uploaded_files: list[Path]) -> IngestStats:
        return await asyncio.to_thread(self._ingest_files, uploaded_files)

    async def ingest_uploaded_files_with_progress(
        self,
        uploaded_files: list[Path],
        progress_callback: Callable[[IngestStats], Awaitable[None]] | None = None,
    ) -> IngestStats:
        aggregate = IngestStats()
        for file_path in uploaded_files:
            file_stats = await asyncio.to_thread(self._ingest_files, [file_path])
            aggregate.files_processed += file_stats.files_processed
            aggregate.chunks_indexed += file_stats.chunks_indexed
            aggregate.skipped_files += file_stats.skipped_files
            if progress_callback is not None:
                await progress_callback(aggregate)
        return aggregate

    def _ingest_files(self, files: list[Path] | tuple[Path, ...] | object) -> IngestStats:
        stats = IngestStats()
        max_bytes = settings.max_file_size_mb * 1024 * 1024

        for file_path in files:
            try:
                if file_path.stat().st_size > max_bytes:
                    stats.skipped_files += 1
                    continue

                text = load_text(file_path)
                logger.warning(
                    "ingest file=%s size_bytes=%s extracted_len=%s preview=%s",
                    file_path,
                    file_path.stat().st_size,
                    len(text),
                    text[:300],
                )
                chunks = chunk_text(text, settings.chunk_size, settings.chunk_overlap)
                if not chunks:
                    stats.skipped_files += 1
                    continue

                document_hash = hashlib.sha256(text.encode("utf-8", errors="ignore")).hexdigest()
                ids = [f"{document_hash}:{idx}" for idx, _ in enumerate(chunks)]
                embeddings = self.embedder.embed(chunks)
                if not (len(ids) == len(embeddings) == len(chunks)):
                    raise RuntimeError(
                        "embedding/upsert length mismatch "
                        f"ids={len(ids)} embeddings={len(embeddings)} chunks={len(chunks)}",
                    )
                metadatas = [
                    {
                        "document_id": document_hash,
                        "source": str(file_path),
                        "filename": file_path.name,
                        "chunk_index": idx,
                    }
                    for idx, _ in enumerate(chunks)
                ]

                self.vectordb.upsert(ids=ids, embeddings=embeddings, documents=chunks, metadatas=metadatas)
                stats.files_processed += 1
                stats.chunks_indexed += len(chunks)
            except (DocumentLoadError, OSError) as exc:
                logger.warning("Skipping file %s due to load/os error: %s", file_path, exc)
                stats.skipped_files += 1
            except Exception as exc:
                logger.exception("Failed ingest for file %s: %s", file_path, exc)
                stats.skipped_files += 1

        return stats

    def list_documents(self) -> list[dict[str, str | int]]:
        payload = self.vectordb.get_all()
        metadatas = payload.get("metadatas") or []
        grouped: dict[str, dict[str, str | int]] = {}
        for metadata in metadatas:
            if not isinstance(metadata, dict):
                continue
            doc_id = str(metadata.get("document_id", "unknown"))
            entry = grouped.get(doc_id)
            if entry is None:
                grouped[doc_id] = {
                    "doc_id": doc_id,
                    "source": str(metadata.get("filename") or metadata.get("source") or "unknown"),
                    "chunks": 1,
                }
            else:
                entry["chunks"] = int(entry["chunks"]) + 1
        return list(grouped.values())

    def delete_document(self, doc_id: str) -> None:
        self.vectordb.delete_by_document_id(doc_id)

    def clear_documents(self) -> None:
        self.vectordb.delete_all()

    async def answer(self, question: str, history: list[ChatTurn] | None = None) -> tuple[str, list[Citation], int]:
        question_embedding_list = await asyncio.to_thread(self.embedder.embed, [question])
        q_embedding = question_embedding_list[0]
        results = await asyncio.to_thread(self.vectordb.query, q_embedding, settings.top_k)

        documents = (results.get("documents") or [[]])[0]
        metadatas = (results.get("metadatas") or [[]])[0]
        ids = (results.get("ids") or [[]])[0]
        distances = (results.get("distances") or [[]])[0]

        if distances:
            filtered = [
                (document, metadata, chunk_id, distance)
                for document, metadata, chunk_id, distance in zip(documents, metadatas, ids, distances)
                if distance is not None and float(distance) <= settings.max_similarity_distance
            ]
            if filtered:
                documents = [item[0] for item in filtered]
                metadatas = [item[1] for item in filtered]
                ids = [item[2] for item in filtered]
            else:
                logger.info(
                    "No results under similarity threshold=%s; raw distances=%s",
                    settings.max_similarity_distance,
                    distances,
                )
                return ("No relevant documents found for this question.", [], 0)

        if not documents:
            logger.info("No documents returned from vector query (top_k=%s)", settings.top_k)
            return (
                "I do not have enough information in the local knowledge base yet. Ingest documents first.",
                [],
                0,
            )

        answer = await self.llm.generate(question, documents, history)
        citations: list[Citation] = []
        for idx, metadata in enumerate(metadatas):
            source = str(metadata.get("source", "unknown"))
            chunk_id = str(ids[idx]) if idx < len(ids) else "unknown"
            citations.append(Citation(source=source, chunk_id=chunk_id))

        return answer, citations, len(documents)
