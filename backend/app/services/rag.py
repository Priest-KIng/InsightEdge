from __future__ import annotations

import asyncio
from dataclasses import dataclass
import hashlib
from pathlib import Path
import re
import time
from typing import AsyncIterator, Awaitable, Callable

import structlog

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

try:
    from pdf2image import convert_from_path
except Exception:
    convert_from_path = None

logger = structlog.get_logger(__name__)


@dataclass
class IngestStats:
    files_processed: int = 0
    chunks_indexed: int = 0
    skipped_files: int = 0


@dataclass(frozen=True)
class IngestFileRef:
    path: Path
    display_name: str | None = None


@dataclass
class RAGAnswer:
    answer: str
    citations: list[Citation]
    context_chunks: int
    model: str
    workspace_id: str
    retrieval_mode: str
    retrieved_chunks: int
    final_context_chunks: int
    latency_ms: float


class RAGService:
    def __init__(self) -> None:
        self.embedder = EmbeddingService(
            settings.embedding_model,
            provider=settings.embedding_provider,
            ollama_base_url=settings.ollama_base_url,
        )
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
                logger.warning(
                    "cross_encoder_disabled",
                    model=settings.cross_encoder_model,
                    error=str(exc),
                )

    @staticmethod
    def normalize_workspace_id(workspace_id: str | None) -> str:
        candidate = (workspace_id or settings.default_workspace_id).strip().lower()
        sanitized = re.sub(r"[^a-z0-9_-]+", "-", candidate).strip("-_")
        if not sanitized:
            return settings.default_workspace_id
        return sanitized[:48]

    async def ingest_path(self, raw_path: str, workspace_id: str | None = None) -> IngestStats:
        resolved_workspace = self.normalize_workspace_id(workspace_id)
        base_dir = settings.ingest_base_dir.resolve()
        requested = Path(raw_path).expanduser()
        candidate = requested if requested.is_absolute() else (base_dir / requested)
        candidate = candidate.resolve()

        if not candidate.exists():
            raise FileNotFoundError(f"Path does not exist: {candidate}")

        if not candidate.is_relative_to(base_dir):
            raise PermissionError(f"Path must be under ingest base directory: {base_dir}")

        return await asyncio.to_thread(self._ingest_files, iter_supported_files(candidate), resolved_workspace)

    async def ingest_uploaded_files(
        self,
        uploaded_files: list[Path | IngestFileRef],
        workspace_id: str | None = None,
    ) -> IngestStats:
        resolved_workspace = self.normalize_workspace_id(workspace_id)
        return await asyncio.to_thread(self._ingest_files, uploaded_files, resolved_workspace)

    async def ingest_uploaded_files_with_progress(
        self,
        uploaded_files: list[Path | IngestFileRef],
        progress_callback: Callable[[IngestStats], Awaitable[None]] | None = None,
        workspace_id: str | None = None,
    ) -> IngestStats:
        resolved_workspace = self.normalize_workspace_id(workspace_id)
        aggregate = IngestStats()
        lock = asyncio.Lock()
        max_workers = max(1, settings.ingest_max_workers)
        semaphore = asyncio.Semaphore(max_workers)

        async def _process_file(file_ref: Path | IngestFileRef) -> None:
            async with semaphore:
                file_stats = await asyncio.to_thread(self._ingest_files, [file_ref], resolved_workspace)
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

    @staticmethod
    def _is_document_overview_query(question: str) -> bool:
        tokens = set(RAGService._tokenize(question))
        document_terms = {
            "document",
            "documents",
            "file",
            "files",
            "upload",
            "uploaded",
            "content",
            "contents",
            "summarize",
            "summary",
            "overview",
        }
        if tokens.intersection(document_terms):
            return True
        lowered = question.lower()
        return "what is in" in lowered or "what does it say" in lowered

    @staticmethod
    def _is_greeting(question: str) -> bool:
        normalized = " ".join(RAGService._tokenize(question))
        return normalized in {"hi", "hello", "hey", "good morning", "good evening", "good afternoon"}

    @staticmethod
    def _is_meta_question(question: str) -> bool:
        lowered = question.lower()
        patterns = [
            "who are you",
            "what can you do",
            "what model",
            "which model",
            "model are you using",
            "what are you",
        ]
        return any(pattern in lowered for pattern in patterns)

    @staticmethod
    def _meta_answer(question: str, selected_model: str) -> str:
        lowered = question.lower()
        if "model" in lowered:
            return f"I am using the selected local Ollama model: `{selected_model}`."
        if "what can you do" in lowered:
            return (
                "I can help you work with locally ingested documents: summarize them, answer questions, "
                "show citations, and keep each workspace separate."
            )
        return "I am InsightEdge, a local-first document assistant that answers from your private knowledge base."

    @staticmethod
    def _source_type_for(filename: str) -> str:
        suffix = Path(filename).suffix.lower().lstrip(".")
        return suffix or "text"

    @staticmethod
    def _extract_page_number(chunk: str) -> int | None:
        match = re.search(r"\[PAGE\s+(\d+)", chunk, flags=re.IGNORECASE)
        return int(match.group(1)) if match else None

    @staticmethod
    def _extract_section_title(chunk: str) -> str | None:
        cleaned = re.sub(r"\[[^\]]+\]", " ", chunk).strip()
        if not cleaned:
            return None
        candidate = cleaned.split(". ")[0].strip()
        if 4 <= len(candidate) <= 90:
            return candidate
        return None

    @staticmethod
    def _short_snippet(text: str, max_chars: int = 360) -> str:
        return " ".join(text.split())[:max_chars].strip()

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
            logger.warning("cross_encoder_rerank_failed", error=str(exc))
            return list(range(len(documents)))

        ranked_indices = sorted(
            range(len(documents)),
            key=lambda idx: float(scores[idx]),
            reverse=True,
        )
        return ranked_indices[: max(settings.top_k, settings.cross_encoder_top_n)]

    async def _build_hyde_query(self, question: str) -> str:
        if not settings.enable_hyde:
            return question

        prompt = (
            "Write a short hypothetical answer (3-6 sentences) that could plausibly answer "
            "the user's question using facts from an unknown document corpus. "
            "Do not mention uncertainty or cite sources.\n\n"
            f"Question: {question}\n\n"
            "Hypothetical answer:"
        )
        try:
            hypothetical = await self.llm.generate_from_prompt(prompt, temperature=0.1)
        except Exception as exc:
            logger.warning("hyde_generation_failed", error=str(exc))
            return question

        cleaned = hypothetical.strip()
        if not cleaned:
            return question
        return cleaned[: settings.hyde_max_chars]

    async def _expand_queries(self, question: str) -> list[str]:
        if not settings.enable_multi_query:
            return [question]

        prompt = (
            "Generate concise alternative search queries for retrieval. "
            "Return each query on its own line with no numbering.\n\n"
            f"Original question: {question}\n\n"
            f"Number of alternatives: {max(1, settings.multi_query_count)}"
        )
        try:
            raw = await self.llm.generate_from_prompt(prompt, temperature=0.2)
        except Exception as exc:
            logger.warning("multi_query_expansion_failed", error=str(exc))
            return [question]

        candidates = [line.strip(" -\t\r\n") for line in raw.splitlines()]
        normalized: list[str] = [question]
        seen = {question.lower()}
        for candidate in candidates:
            if not candidate:
                continue
            key = candidate.lower()
            if key in seen:
                continue
            seen.add(key)
            normalized.append(candidate)
            if len(normalized) >= max(1, settings.multi_query_count) + 1:
                break
        return normalized

    @staticmethod
    def _document_hash(source: str, text: str, workspace_id: str) -> str:
        doc_key = f"{workspace_id}:{source}\n{text}"
        return hashlib.sha256(doc_key.encode("utf-8", errors="ignore")).hexdigest()

    def _prepare_pdf_page_images(self, file_path: Path, workspace_id: str, document_hash: str) -> list[str]:
        if convert_from_path is None:
            return []

        try:
            images = convert_from_path(
                str(file_path),
                first_page=1,
                last_page=max(1, settings.vlm_max_pages),
                dpi=max(72, settings.vlm_image_dpi),
            )
        except Exception as exc:
            logger.warning("vlm_pdf_render_failed", file=str(file_path), error=str(exc))
            return []

        if not images:
            return []

        image_dir = settings.data_dir / "vlm_pages" / workspace_id / document_hash
        image_dir.mkdir(parents=True, exist_ok=True)
        saved_paths: list[str] = []
        for idx, image in enumerate(images, start=1):
            path = image_dir / f"page_{idx}.jpg"
            try:
                image.convert("RGB").save(path, format="JPEG", quality=88)
                saved_paths.append(str(path))
            except Exception as exc:
                logger.warning("vlm_page_save_failed", file=str(file_path), page=idx, error=str(exc))
        return saved_paths

    @staticmethod
    def _coerce_file_ref(file_ref: Path | IngestFileRef) -> tuple[Path, str]:
        if isinstance(file_ref, IngestFileRef):
            display_name = (file_ref.display_name or file_ref.path.name).strip() or file_ref.path.name
            return file_ref.path, display_name
        return file_ref, file_ref.name

    def _ingest_files(
        self,
        files: list[Path | IngestFileRef] | tuple[Path | IngestFileRef, ...] | object,
        workspace_id: str,
    ) -> IngestStats:
        stats = IngestStats()
        max_bytes = settings.max_file_size_mb * 1024 * 1024

        for file_ref in files:
            file_path, display_name = self._coerce_file_ref(file_ref)
            try:
                started = time.perf_counter()
                if file_path.stat().st_size > max_bytes:
                    stats.skipped_files += 1
                    continue

                text = load_text(file_path)
                extraction_ms = round((time.perf_counter() - started) * 1000, 2)
                logger.info(
                    "ingest_file_loaded",
                    file=str(file_path),
                    size_bytes=file_path.stat().st_size,
                    extracted_len=len(text),
                    extraction_ms=extraction_ms,
                    preview=text[:300],
                )
                page_image_paths: list[str] = []
                if settings.enable_vlm_pdf_assist and file_path.suffix.lower() == ".pdf":
                    doc_hash = self._document_hash(display_name, text, workspace_id)
                    page_image_paths = self._prepare_pdf_page_images(file_path, workspace_id, doc_hash)
                chunk_count = self._upsert_text_document(
                    source=display_name,
                    filename=display_name,
                    text=text,
                    workspace_id=workspace_id,
                    page_image_paths=page_image_paths,
                )
                if chunk_count == 0:
                    stats.skipped_files += 1
                    continue

                stats.files_processed += 1
                stats.chunks_indexed += chunk_count
            except (DocumentLoadError, OSError) as exc:
                logger.warning("ingest_file_skipped", file=str(file_path), error=str(exc))
                stats.skipped_files += 1
            except Exception as exc:
                logger.exception("ingest_file_failed", file=str(file_path), error=str(exc))
                stats.skipped_files += 1

        return stats

    def _ingest_text_documents(
        self,
        documents: list[tuple[str, str, str]],
        workspace_id: str,
    ) -> IngestStats:
        stats = IngestStats()
        for source, filename, text in documents:
            try:
                chunk_count = self._upsert_text_document(
                    source=source,
                    filename=filename,
                    text=text,
                    workspace_id=workspace_id,
                )
                if chunk_count == 0:
                    stats.skipped_files += 1
                    continue
                stats.files_processed += 1
                stats.chunks_indexed += chunk_count
            except Exception as exc:
                logger.exception("ingest_source_failed", source=source, error=str(exc))
                stats.skipped_files += 1
        return stats

    def _upsert_text_document(
        self,
        source: str,
        filename: str,
        text: str,
        workspace_id: str,
        page_image_paths: list[str] | None = None,
    ) -> int:
        started = time.perf_counter()
        chunks = chunk_text(text, settings.chunk_size, settings.chunk_overlap)
        if not chunks:
            return 0
        parent_text = text[: settings.parent_document_max_chars].strip()
        normalized_text = " ".join(text.split())

        document_hash = self._document_hash(source, text, workspace_id)
        file_hash = hashlib.sha256(text.encode("utf-8", errors="ignore")).hexdigest()
        image_paths_blob = ";".join(page_image_paths or [])
        ids = [f"{document_hash}:{idx}" for idx, _ in enumerate(chunks)]
        embed_started = time.perf_counter()
        embeddings = self.embedder.embed(chunks)
        embed_ms = round((time.perf_counter() - embed_started) * 1000, 2)
        if not (len(ids) == len(embeddings) == len(chunks)):
            raise RuntimeError(
                "embedding/upsert length mismatch "
                f"ids={len(ids)} embeddings={len(embeddings)} chunks={len(chunks)}",
            )
        offsets: list[tuple[int | None, int | None]] = []
        cursor = 0
        for chunk in chunks:
            index = normalized_text.find(chunk, cursor)
            if index < 0:
                index = normalized_text.find(chunk)
            if index < 0:
                offsets.append((None, None))
            else:
                offsets.append((index, index + len(chunk)))
                cursor = index + len(chunk)
        metadatas = [
            {
                "document_id": document_hash,
                "source": source,
                "filename": filename,
                "chunk_index": idx,
                "workspace_id": workspace_id,
                "parent_text": parent_text,
                "page_image_paths": image_paths_blob,
                "file_hash": file_hash,
                "source_type": self._source_type_for(filename),
                "page_number": self._extract_page_number(chunk),
                "section_title": self._extract_section_title(chunk),
                "ocr_used": "[OCR]" in chunk.upper(),
                "table_used": "[PAGE" in chunk.upper() and "TABLE" in chunk.upper(),
                "snippet": self._short_snippet(chunk),
                "start_char": offsets[idx][0],
                "end_char": offsets[idx][1],
            }
            for idx, chunk in enumerate(chunks)
        ]
        upsert_started = time.perf_counter()
        self.vectordb.upsert(
            ids=ids,
            embeddings=embeddings,
            documents=chunks,
            metadatas=metadatas,
            workspace_id=workspace_id,
        )
        logger.info(
            "ingest_document_indexed",
            source=filename,
            workspace_id=workspace_id,
            document_id=document_hash,
            chunks=len(chunks),
            embed_ms=embed_ms,
            upsert_ms=round((time.perf_counter() - upsert_started) * 1000, 2),
            total_ms=round((time.perf_counter() - started) * 1000, 2),
        )
        return len(chunks)

    def list_documents(self, workspace_id: str | None = None) -> list[dict[str, str | int]]:
        resolved_workspace = self.normalize_workspace_id(workspace_id)
        payload = self.vectordb.get_all(resolved_workspace)
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

    def delete_document(self, doc_id: str, workspace_id: str | None = None) -> None:
        resolved_workspace = self.normalize_workspace_id(workspace_id)
        self.vectordb.delete_by_document_id(doc_id, resolved_workspace)

    def clear_documents(self, workspace_id: str | None = None) -> None:
        resolved_workspace = self.normalize_workspace_id(workspace_id)
        self.vectordb.delete_all(resolved_workspace)

    def delete_workspace(self, workspace_id: str | None = None) -> None:
        resolved_workspace = self.normalize_workspace_id(workspace_id)
        default_workspace = self.normalize_workspace_id(settings.default_workspace_id)
        if resolved_workspace == default_workspace:
            raise ValueError("The default workspace cannot be deleted")
        self.vectordb.delete_workspace(resolved_workspace)

    def list_workspaces(self) -> list[str]:
        workspaces = self.vectordb.list_workspaces()
        default_workspace = self.normalize_workspace_id(settings.default_workspace_id)
        if default_workspace not in workspaces:
            workspaces.insert(0, default_workspace)
        return sorted(set(workspaces))

    async def retrieve_context(
        self,
        question: str,
        workspace_id: str | None = None,
        retrieval_mode: str = "hybrid",
        apply_compression: bool = True,
    ) -> tuple[list[str], list[dict[str, object]], list[str], list[float]]:
        resolved_workspace = self.normalize_workspace_id(workspace_id)
        started = time.perf_counter()
        candidate_k = max(settings.top_k, settings.retrieval_candidate_k)
        queries = await self._expand_queries(question)
        merged_results: dict[str, tuple[str, dict[str, object], float]] = {}

        if retrieval_mode == "lexical":
            payload = await asyncio.to_thread(self.vectordb.get_all, resolved_workspace)
            all_documents = [str(item) for item in (payload.get("documents") or [])]
            all_metadatas = [
                item if isinstance(item, dict) else {}
                for item in (payload.get("metadatas") or [])
            ]
            all_ids = [str(item) for item in (payload.get("ids") or [])]
            question_terms = set(self._tokenize(question))
            lexical_rows: list[tuple[int, int]] = []
            for idx, document in enumerate(all_documents):
                overlap = len(question_terms.intersection(set(self._tokenize(document))))
                lexical_rows.append((idx, overlap))
            positive_rows = [(idx, score) for idx, score in lexical_rows if score > 0]
            if not positive_rows and self._is_document_overview_query(question):
                positive_rows = lexical_rows
            for idx, score in sorted(positive_rows, key=lambda item: item[1], reverse=True)[:candidate_k]:
                distance = 1.0 / (1.0 + score) if score > 0 else 1.0
                merged_results[all_ids[idx]] = (all_documents[idx], all_metadatas[idx], distance)
        else:
            for query in queries:
                retrieval_query = await self._build_hyde_query(query)
                question_embedding_list = await asyncio.to_thread(self.embedder.embed, [retrieval_query])
                q_embedding = question_embedding_list[0]
                results = await asyncio.to_thread(self.vectordb.query, q_embedding, candidate_k, resolved_workspace)

                documents_batch = list((results.get("documents") or [[]])[0])
                metadatas_batch = list((results.get("metadatas") or [[]])[0])
                ids_batch = [str(item) for item in ((results.get("ids") or [[]])[0])]
                raw_distances_batch = list((results.get("distances") or [[]])[0])
                distances_batch = [float(item) if item is not None else float("inf") for item in raw_distances_batch]

                for document, metadata, chunk_id, distance in zip(
                    documents_batch,
                    metadatas_batch,
                    ids_batch,
                    distances_batch,
                ):
                    normalized_meta = metadata if isinstance(metadata, dict) else {}
                    existing = merged_results.get(chunk_id)
                    if existing is None or distance < existing[2]:
                        merged_results[chunk_id] = (str(document), normalized_meta, float(distance))

        ranked = sorted(merged_results.items(), key=lambda item: item[1][2])
        documents = [item[1][0] for item in ranked]
        metadatas = [item[1][1] for item in ranked]
        ids = [item[0] for item in ranked]
        distances = [item[1][2] for item in ranked]

        if distances and retrieval_mode != "lexical":
            filtered = [
                (document, metadata, chunk_id, distance)
                for document, metadata, chunk_id, distance in zip(documents, metadatas, ids, distances)
                if distance is not None and float(distance) <= settings.max_similarity_distance
            ]
            if filtered:
                documents = [str(item[0]) for item in filtered]
                metadatas = [item[1] if isinstance(item[1], dict) else {} for item in filtered]
                ids = [str(item[2]) for item in filtered]
                distances = [float(item[3]) for item in filtered]
            elif self._is_document_overview_query(question):
                fallback_count = min(settings.top_k, len(documents))
                logger.info(
                    "retrieval_threshold_relaxed_for_document_overview",
                    question=question,
                    workspace_id=resolved_workspace,
                    threshold=settings.max_similarity_distance,
                    raw_distances=distances,
                    fallback_chunks=fallback_count,
                    sources=[
                        str(metadata.get("filename") or metadata.get("source") or "unknown")
                        for metadata in metadatas[:fallback_count]
                        if isinstance(metadata, dict)
                    ],
                )
                documents = documents[:fallback_count]
                metadatas = [
                    metadata if isinstance(metadata, dict) else {}
                    for metadata in metadatas[:fallback_count]
                ]
                ids = ids[:fallback_count]
                distances = distances[:fallback_count]
            else:
                logger.info(
                    "no_results_under_similarity_threshold",
                    question=question,
                    workspace_id=resolved_workspace,
                    threshold=settings.max_similarity_distance,
                    raw_distances=distances,
                )
                return [], [], [], []

        if settings.enable_parent_document_retrieval:
            parent_documents: list[str] = []
            for document, metadata in zip(documents, metadatas):
                if isinstance(metadata, dict):
                    parent_text = str(metadata.get("parent_text") or "").strip()
                    if parent_text:
                        parent_documents.append(parent_text)
                        continue
                parent_documents.append(str(document))
            documents = parent_documents

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

        if retrieval_mode in {"lexical", "hybrid", "hybrid_rerank", "hybrid_compression"}:
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
                if retrieval_mode == "lexical":
                    score = 1.0 / (rrf_k + l_rank)
                else:
                    score = (1.0 / (rrf_k + v_rank)) + (1.0 / (rrf_k + l_rank))
                fused.append((idx, score))

            fused_indices = [idx for idx, _ in sorted(fused, key=lambda item: item[1], reverse=True)]

            documents = [documents[idx] for idx in fused_indices]
            metadatas = [metadatas[idx] for idx in fused_indices]
            ids = [ids[idx] for idx in fused_indices]
            distances = [distances[idx] for idx in fused_indices]

        # Optional neural reranking.
        if retrieval_mode in {"hybrid_rerank"}:
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
        if apply_compression or retrieval_mode == "hybrid_compression":
            documents = [self._compress_context(question, document) for document in documents]
        logger.info(
            "retrieval_completed",
            question=question,
            workspace_id=resolved_workspace,
            retrieval_mode=retrieval_mode,
            retrieved_chunks=len(documents),
            sources=[
                str(metadata.get("filename") or metadata.get("source") or "unknown")
                for metadata in metadatas
                if isinstance(metadata, dict)
            ],
            distances=distances,
            context_chars=sum(len(document) for document in documents),
            latency_ms=round((time.perf_counter() - started) * 1000, 2),
        )

        return documents, metadatas, ids, distances

    async def _retrieve_context(
        self,
        question: str,
        workspace_id: str | None = None,
    ) -> tuple[list[str], list[dict[str, object]], list[str], list[float]]:
        return await self.retrieve_context(question, workspace_id, retrieval_mode="hybrid")

    async def _self_rag_follow_up_query(self, question: str, documents: list[str]) -> str | None:
        if not settings.enable_self_rag:
            return None
        if not documents:
            return None

        context_preview = "\n\n".join([f"[{idx + 1}] {doc}" for idx, doc in enumerate(documents[:3])])
        prompt = (
            "You are validating retrieval quality.\n"
            "Given a user question and retrieved context, decide if another retrieval pass is needed.\n"
            "Respond with exactly two lines:\n"
            "SUFFICIENT: yes|no\n"
            "FOLLOW_UP_QUERY: <query if needed, else empty>\n\n"
            f"QUESTION: {question}\n\n"
            f"CONTEXT:\n{context_preview}\n"
        )
        try:
            decision = await self.llm.generate_from_prompt(prompt, temperature=0.0)
        except Exception as exc:
            logger.warning("self_rag_decision_failed", error=str(exc))
            return None

        sufficient_match = re.search(r"SUFFICIENT:\s*(yes|no)", decision, flags=re.IGNORECASE)
        follow_up_match = re.search(r"FOLLOW_UP_QUERY:\s*(.*)", decision, flags=re.IGNORECASE)
        is_sufficient = sufficient_match and sufficient_match.group(1).lower() == "yes"
        if is_sufficient:
            return None
        follow_up = follow_up_match.group(1).strip() if follow_up_match else ""
        if not follow_up or follow_up.lower() == question.lower():
            return None
        return follow_up

    async def _retrieve_with_self_rag(
        self,
        question: str,
        workspace_id: str | None = None,
    ) -> tuple[list[str], list[dict[str, object]], list[str], list[float]]:
        documents, metadatas, ids, distances = await self._retrieve_context(question, workspace_id)
        if not settings.enable_self_rag or not documents:
            return documents, metadatas, ids, distances

        followups = max(0, settings.self_rag_max_followups)
        current_question = question
        for _ in range(followups):
            follow_up_query = await self._self_rag_follow_up_query(current_question, documents)
            if not follow_up_query:
                break
            extra_docs, extra_meta, extra_ids, extra_distances = await self._retrieve_context(
                follow_up_query,
                workspace_id,
            )
            if not extra_docs:
                break
            existing_ids = set(ids)
            for doc, meta, chunk_id, distance in zip(extra_docs, extra_meta, extra_ids, extra_distances):
                if chunk_id in existing_ids:
                    continue
                documents.append(doc)
                metadatas.append(meta)
                ids.append(chunk_id)
                distances.append(distance)
                existing_ids.add(chunk_id)
            current_question = follow_up_query

        if len(documents) > settings.top_k:
            documents = documents[: settings.top_k]
            metadatas = metadatas[: settings.top_k]
            ids = ids[: settings.top_k]
            distances = distances[: settings.top_k]

        return documents, metadatas, ids, distances

    @staticmethod
    def _build_citations(
        metadatas: list[dict[str, object]],
        ids: list[str],
        documents: list[str] | None = None,
        distances: list[float] | None = None,
    ) -> list[Citation]:
        citations: list[Citation] = []
        for idx, metadata in enumerate(metadatas):
            source = str(metadata.get("filename") or metadata.get("source") or "unknown")
            chunk_id = str(ids[idx]) if idx < len(ids) else "unknown"
            distance = float(distances[idx]) if distances and idx < len(distances) else None
            citations.append(
                Citation(
                    source=source,
                    chunk_id=chunk_id,
                    document_id=str(metadata.get("document_id") or "") or None,
                    filename=str(metadata.get("filename") or source),
                    page_number=int(metadata["page_number"]) if metadata.get("page_number") is not None else None,
                    section_title=str(metadata.get("section_title") or "") or None,
                    snippet=str(metadata.get("snippet") or (documents[idx] if documents and idx < len(documents) else ""))[:500]
                    or None,
                    score=(1.0 / (1.0 + distance)) if distance is not None else None,
                    retrieval_rank=idx + 1,
                    source_type=str(metadata.get("source_type") or "") or None,
                    ocr_used=bool(metadata.get("ocr_used", False)),
                    start_char=int(metadata["start_char"]) if metadata.get("start_char") is not None else None,
                    end_char=int(metadata["end_char"]) if metadata.get("end_char") is not None else None,
                ),
            )
        return citations

    async def _build_vlm_context(self, question: str, metadatas: list[dict[str, object]]) -> str | None:
        if not settings.enable_vlm_pdf_assist:
            return None

        candidate_paths: list[str] = []
        for metadata in metadatas:
            if not isinstance(metadata, dict):
                continue
            paths_blob = str(metadata.get("page_image_paths") or "").strip()
            if not paths_blob:
                continue
            for raw in paths_blob.split(";"):
                raw = raw.strip()
                if not raw:
                    continue
                path = Path(raw)
                if path.exists():
                    candidate_paths.append(str(path))
            if candidate_paths:
                break

        if not candidate_paths:
            return None

        limited_paths = candidate_paths[: max(1, settings.vlm_max_pages)]
        try:
            vision_summary = await self.llm.generate_vision_summary(
                question=question,
                image_paths=limited_paths,
                model_name=settings.vlm_model,
            )
        except Exception as exc:
            logger.warning("vlm_context_generation_failed", error=str(exc))
            return None

        if not vision_summary:
            return None
        return f"[VISION ASSIST SUMMARY]\n{vision_summary}"

    async def answer_stream(
        self,
        question: str,
        history: list[ChatTurn] | None = None,
        system_prompt: str | None = None,
        workspace_id: str | None = None,
        llm_model: str | None = None,
    ) -> tuple[AsyncIterator[str], list[Citation], int, dict[str, object]]:
        started = time.perf_counter()
        selected_model = (llm_model or self.llm.model_name).strip()
        resolved_workspace = self.normalize_workspace_id(workspace_id)
        if self._is_greeting(question):
            async def _greeting() -> AsyncIterator[str]:
                yield "Hi. I am ready to help with your local documents."

            return _greeting(), [], 0, {
                "model": selected_model,
                "workspace_id": resolved_workspace,
                "retrieval_mode": "none",
                "retrieved_chunks": 0,
                "final_context_chunks": 0,
                "latency_ms": round((time.perf_counter() - started) * 1000, 2),
            }
        if self._is_meta_question(question):
            async def _meta() -> AsyncIterator[str]:
                yield self._meta_answer(question, selected_model)

            return _meta(), [], 0, {
                "model": selected_model,
                "workspace_id": resolved_workspace,
                "retrieval_mode": "none",
                "retrieved_chunks": 0,
                "final_context_chunks": 0,
                "latency_ms": round((time.perf_counter() - started) * 1000, 2),
            }

        documents, metadatas, ids, distances = await self._retrieve_with_self_rag(question, workspace_id)

        if not documents:
            has_documents = bool(self.list_documents(resolved_workspace))
            fallback_message = (
                "I found ingested documents in this workspace, but no relevant chunks matched that question. "
                "Try asking about the uploaded document's contents or upload a more relevant document."
                if has_documents
                else "I do not have enough information in the local knowledge base yet. Ingest documents first."
            )

            async def _fallback() -> AsyncIterator[str]:
                yield fallback_message

            return _fallback(), [], 0, {
                "model": selected_model,
                "workspace_id": resolved_workspace,
                "retrieval_mode": "hybrid",
                "retrieved_chunks": 0,
                "final_context_chunks": 0,
                "latency_ms": round((time.perf_counter() - started) * 1000, 2),
            }

        vlm_context = await self._build_vlm_context(question, metadatas)
        if vlm_context:
            documents = [*documents, vlm_context]

        stream = self.llm.generate_stream(
            question,
            documents,
            history,
            system_prompt,
            model_name=llm_model,
        )
        citations = self._build_citations(metadatas, ids, documents, distances)
        return stream, citations, len(documents), {
            "model": selected_model,
            "workspace_id": resolved_workspace,
            "retrieval_mode": "hybrid",
            "retrieved_chunks": len(ids),
            "final_context_chunks": len(documents),
            "latency_ms": round((time.perf_counter() - started) * 1000, 2),
        }

    async def answer(
        self,
        question: str,
        history: list[ChatTurn] | None = None,
        system_prompt: str | None = None,
        workspace_id: str | None = None,
        llm_model: str | None = None,
    ) -> RAGAnswer:
        started = time.perf_counter()
        selected_model = (llm_model or self.llm.model_name).strip()
        resolved_workspace = self.normalize_workspace_id(workspace_id)
        if self._is_greeting(question):
            return RAGAnswer(
                answer="Hi. I am ready to help with your local documents.",
                citations=[],
                context_chunks=0,
                model=selected_model,
                workspace_id=resolved_workspace,
                retrieval_mode="none",
                retrieved_chunks=0,
                final_context_chunks=0,
                latency_ms=round((time.perf_counter() - started) * 1000, 2),
            )
        if self._is_meta_question(question):
            return RAGAnswer(
                answer=self._meta_answer(question, selected_model),
                citations=[],
                context_chunks=0,
                model=selected_model,
                workspace_id=resolved_workspace,
                retrieval_mode="none",
                retrieved_chunks=0,
                final_context_chunks=0,
                latency_ms=round((time.perf_counter() - started) * 1000, 2),
            )

        documents, metadatas, ids, distances = await self._retrieve_with_self_rag(question, workspace_id)

        if not documents:
            logger.info("no_documents_from_vector_query", top_k=settings.top_k)
            if self.list_documents(resolved_workspace):
                return RAGAnswer(
                    answer=(
                        "I found ingested documents in this workspace, but no relevant chunks matched that question. "
                        "Try asking about the uploaded document's contents or upload a more relevant document."
                    ),
                    citations=[],
                    context_chunks=0,
                    model=selected_model,
                    workspace_id=resolved_workspace,
                    retrieval_mode="hybrid",
                    retrieved_chunks=0,
                    final_context_chunks=0,
                    latency_ms=round((time.perf_counter() - started) * 1000, 2),
                )
            return RAGAnswer(
                answer="I do not have enough information in the local knowledge base yet. Ingest documents first.",
                citations=[],
                context_chunks=0,
                model=selected_model,
                workspace_id=resolved_workspace,
                retrieval_mode="hybrid",
                retrieved_chunks=0,
                final_context_chunks=0,
                latency_ms=round((time.perf_counter() - started) * 1000, 2),
            )

        vlm_context = await self._build_vlm_context(question, metadatas)
        if vlm_context:
            documents = [*documents, vlm_context]

        answer = await self.llm.generate(
            question,
            documents,
            history,
            system_prompt,
            model_name=llm_model,
        )
        citations = self._build_citations(metadatas, ids, documents, distances)
        return RAGAnswer(
            answer=answer,
            citations=citations,
            context_chunks=len(documents),
            model=selected_model,
            workspace_id=resolved_workspace,
            retrieval_mode="hybrid",
            retrieved_chunks=len(ids),
            final_context_chunks=len(documents),
            latency_ms=round((time.perf_counter() - started) * 1000, 2),
        )
