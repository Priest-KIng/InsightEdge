from __future__ import annotations

import asyncio
from dataclasses import dataclass
import hashlib
import logging
from pathlib import Path
import re
from typing import AsyncIterator, Awaitable, Callable

from app.config import settings
from app.schemas import ChatTurn, Citation
from app.services.chunker import chunk_text
from app.services.embeddings import EmbeddingService
from app.services.llm import LocalLLMService
from app.services.loader import DocumentLoadError, iter_supported_files, load_text
from app.services.vector_store import VectorStore

try:
    from sentence_transformers import CrossEncoder
except Exception:
    CrossEncoder = None

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
        self.reranker = None
        if settings.cross_encoder_model and CrossEncoder is not None:
            try:
                self.reranker = CrossEncoder(settings.cross_encoder_model)
            except Exception as exc:
                logger.warning("Cross-encoder disabled, failed to load model %s: %s", settings.cross_encoder_model, exc)

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
        lock = asyncio.Lock()
        max_workers = max(1, settings.ingest_max_workers)
        semaphore = asyncio.Semaphore(max_workers)

        async def _process_file(file_path: Path) -> None:
            async with semaphore:
                file_stats = await asyncio.to_thread(self._ingest_files, [file_path])
                async with lock:
                    aggregate.files_processed += file_stats.files_processed
                    aggregate.chunks_indexed += file_stats.chunks_indexed
                    aggregate.skipped_files += file_stats.skipped_files
                    if progress_callback is not None:
                        await progress_callback(aggregate)

        await asyncio.gather(*[_process_file(path) for path in uploaded_files])
        return aggregate

    @staticmethod
    def _tokenize(text: str) -> list[str]:
        return re.findall(r"[a-zA-Z0-9_]+", text.lower())

    def _compress_context(self, question: str, document: str) -> str:
        if not document.strip():
            return document

        sentences = re.split(r"(?<=[.!?])\s+", document)
        if len(sentences) <= settings.context_compression_max_sentences:
            return document[: settings.context_compression_max_chars]

        query_terms = set(self._tokenize(question))
        scored: list[tuple[float, str]] = []
        for sentence in sentences:
            sentence = sentence.strip()
            if not sentence:
                continue
            sentence_terms = set(self._tokenize(sentence))
            overlap = len(query_terms.intersection(sentence_terms))
            score = float(overlap) + min(len(sentence) / 500.0, 1.0)
            scored.append((score, sentence))

        if not scored:
            return document[: settings.context_compression_max_chars]

        ranked = [item[1] for item in sorted(scored, key=lambda x: x[0], reverse=True)]
        selected = ranked[: settings.context_compression_max_sentences]
        compressed = " ".join(selected).strip()
        return compressed[: settings.context_compression_max_chars]

    def _rerank_with_cross_encoder(self, question: str, documents: list[str]) -> list[int]:
        if not documents:
            return []
        if self.reranker is None:
            return list(range(len(documents)))

        pairs = [[question, doc] for doc in documents]
        try:
            scores = self.reranker.predict(pairs)
        except Exception as exc:
            logger.warning("Cross-encoder rerank failed: %s", exc)
            return list(range(len(documents)))

        ranked_indices = sorted(
            range(len(documents)),
            key=lambda idx: float(scores[idx]),
            reverse=True,
        )
        return ranked_indices[: max(settings.top_k, settings.cross_encoder_top_n)]

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

    async def _retrieve_context(
        self,
        question: str,
    ) -> tuple[list[str], list[dict[str, object]], list[str], list[float]]:
        question_embedding_list = await asyncio.to_thread(self.embedder.embed, [question])
        q_embedding = question_embedding_list[0]
        candidate_k = max(settings.top_k, settings.retrieval_candidate_k)
        results = await asyncio.to_thread(self.vectordb.query, q_embedding, candidate_k)

        documents = list((results.get("documents") or [[]])[0])
        metadatas = list((results.get("metadatas") or [[]])[0])
        ids = [str(item) for item in ((results.get("ids") or [[]])[0])]
        raw_distances = list((results.get("distances") or [[]])[0])
        distances = [float(item) if item is not None else float("inf") for item in raw_distances]

        if distances:
            filtered = [
                (document, metadata, chunk_id, distance)
                for document, metadata, chunk_id, distance in zip(documents, metadatas, ids, distances)
                if distance is not None and float(distance) <= settings.max_similarity_distance
            ]
            if filtered:
                documents = [str(item[0]) for item in filtered]
                metadatas = [item[1] if isinstance(item[1], dict) else {} for item in filtered]
                ids = [str(item[2]) for item in filtered]
            else:
                logger.info(
                    "No results under similarity threshold=%s; raw distances=%s",
                    settings.max_similarity_distance,
                    distances,
                )
                return [], [], [], []

        # Deduplicate repeated chunks by normalized text hash.
        dedup_docs: list[str] = []
        dedup_meta: list[dict[str, object]] = []
        dedup_ids: list[str] = []
        dedup_distances: list[float] = []
        seen_hashes: set[str] = set()
        for document, metadata, chunk_id, distance in zip(documents, metadatas, ids, distances):
            doc_text = str(document)
            digest = hashlib.sha256(doc_text.strip().lower().encode("utf-8", errors="ignore")).hexdigest()
            if digest in seen_hashes:
                continue
            seen_hashes.add(digest)
            dedup_docs.append(doc_text)
            dedup_meta.append(metadata if isinstance(metadata, dict) else {})
            dedup_ids.append(str(chunk_id))
            dedup_distances.append(float(distance))

        documents, metadatas, ids, distances = dedup_docs, dedup_meta, dedup_ids, dedup_distances

        # Hybrid scoring using reciprocal-rank fusion between vector rank and lexical overlap rank.
        question_terms = set(self._tokenize(question))
        lexical_scores: list[tuple[int, int]] = []
        for idx, document in enumerate(documents):
            doc_terms = set(self._tokenize(document))
            overlap = len(question_terms.intersection(doc_terms))
            lexical_scores.append((idx, overlap))

        lexical_rank = {
            idx: rank + 1
            for rank, (idx, _) in enumerate(
                sorted(lexical_scores, key=lambda item: item[1], reverse=True),
            )
        }
        vector_rank = {idx: rank + 1 for rank, idx in enumerate(range(len(documents)))}

        rrf_k = max(1, settings.hybrid_rrf_k)
        fused = []
        for idx in range(len(documents)):
            v_rank = vector_rank.get(idx, len(documents) + 1)
            l_rank = lexical_rank.get(idx, len(documents) + 1)
            score = (1.0 / (rrf_k + v_rank)) + (1.0 / (rrf_k + l_rank))
            fused.append((idx, score))

        fused_indices = [idx for idx, _ in sorted(fused, key=lambda item: item[1], reverse=True)]

        documents = [documents[idx] for idx in fused_indices]
        metadatas = [metadatas[idx] for idx in fused_indices]
        ids = [ids[idx] for idx in fused_indices]
        distances = [distances[idx] for idx in fused_indices]

        # Optional neural reranking.
        reranked_indices = self._rerank_with_cross_encoder(question, documents)
        documents = [documents[idx] for idx in reranked_indices]
        metadatas = [metadatas[idx] for idx in reranked_indices]
        ids = [ids[idx] for idx in reranked_indices]
        distances = [distances[idx] for idx in reranked_indices]

        # Final top-k selection and contextual compression.
        documents = documents[: settings.top_k]
        metadatas = metadatas[: settings.top_k]
        ids = ids[: settings.top_k]
        distances = distances[: settings.top_k]
        documents = [self._compress_context(question, document) for document in documents]

        return documents, metadatas, ids, distances

    @staticmethod
    def _build_citations(metadatas: list[dict[str, object]], ids: list[str]) -> list[Citation]:
        citations: list[Citation] = []
        for idx, metadata in enumerate(metadatas):
            source = str(metadata.get("filename") or metadata.get("source") or "unknown")
            chunk_id = str(ids[idx]) if idx < len(ids) else "unknown"
            citations.append(Citation(source=source, chunk_id=chunk_id))
        return citations

    async def answer_stream(
        self,
        question: str,
        history: list[ChatTurn] | None = None,
        system_prompt: str | None = None,
    ) -> tuple[AsyncIterator[str], list[Citation], int]:
        documents, metadatas, ids, _ = await self._retrieve_context(question)

        if not documents:
            async def _fallback() -> AsyncIterator[str]:
                yield "I do not have enough information in the local knowledge base yet. Ingest documents first."

            return _fallback(), [], 0

        stream = self.llm.generate_stream(question, documents, history, system_prompt)
        citations = self._build_citations(metadatas, ids)
        return stream, citations, len(documents)

    async def answer(
        self,
        question: str,
        history: list[ChatTurn] | None = None,
        system_prompt: str | None = None,
    ) -> tuple[str, list[Citation], int]:
        documents, metadatas, ids, _ = await self._retrieve_context(question)

        if not documents:
            logger.info("No documents returned from vector query (top_k=%s)", settings.top_k)
            return (
                "I do not have enough information in the local knowledge base yet. Ingest documents first.",
                [],
                0,
            )

        answer = await self.llm.generate(question, documents, history, system_prompt)
        citations = self._build_citations(metadatas, ids)
        return answer, citations, len(documents)
