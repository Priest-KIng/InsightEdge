from __future__ import annotations

import asyncio
from dataclasses import dataclass
import hashlib
from pathlib import Path
import re
from typing import AsyncIterator, Awaitable, Callable
from urllib.parse import urlparse

from bs4 import BeautifulSoup
import httpx
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
        uploaded_files: list[Path],
        workspace_id: str | None = None,
    ) -> IngestStats:
        resolved_workspace = self.normalize_workspace_id(workspace_id)
        return await asyncio.to_thread(self._ingest_files, uploaded_files, resolved_workspace)

    async def ingest_url(self, url: str, workspace_id: str | None = None) -> IngestStats:
        resolved_workspace = self.normalize_workspace_id(workspace_id)
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"}:
            raise ValueError("URL must start with http:// or https://")
        if not parsed.netloc:
            raise ValueError("URL must include a valid host")

        async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
            response = await client.get(url)
            response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")
        text = soup.get_text(separator="\n", strip=True)
        source_name = parsed.netloc + (parsed.path or "")
        source_name = source_name.strip("/") or parsed.netloc or url

        return await asyncio.to_thread(
            self._ingest_text_documents,
            [(url, source_name, text)],
            resolved_workspace,
        )

    async def ingest_uploaded_files_with_progress(
        self,
        uploaded_files: list[Path],
        progress_callback: Callable[[IngestStats], Awaitable[None]] | None = None,
        workspace_id: str | None = None,
    ) -> IngestStats:
        resolved_workspace = self.normalize_workspace_id(workspace_id)
        aggregate = IngestStats()
        lock = asyncio.Lock()
        max_workers = max(1, settings.ingest_max_workers)
        semaphore = asyncio.Semaphore(max_workers)

        async def _process_file(file_path: Path) -> None:
            async with semaphore:
                file_stats = await asyncio.to_thread(self._ingest_files, [file_path], resolved_workspace)
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

    def _ingest_files(
        self,
        files: list[Path] | tuple[Path, ...] | object,
        workspace_id: str,
    ) -> IngestStats:
        stats = IngestStats()
        max_bytes = settings.max_file_size_mb * 1024 * 1024

        for file_path in files:
            try:
                if file_path.stat().st_size > max_bytes:
                    stats.skipped_files += 1
                    continue

                text = load_text(file_path)
                logger.info(
                    "ingest_file_loaded",
                    file=str(file_path),
                    size_bytes=file_path.stat().st_size,
                    extracted_len=len(text),
                    preview=text[:300],
                )
                page_image_paths: list[str] = []
                if settings.enable_vlm_pdf_assist and file_path.suffix.lower() == ".pdf":
                    doc_hash = self._document_hash(str(file_path), text, workspace_id)
                    page_image_paths = self._prepare_pdf_page_images(file_path, workspace_id, doc_hash)
                chunk_count = self._upsert_text_document(
                    source=str(file_path),
                    filename=file_path.name,
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
        chunks = chunk_text(text, settings.chunk_size, settings.chunk_overlap)
        if not chunks:
            return 0
        parent_text = text[: settings.parent_document_max_chars].strip()

        document_hash = self._document_hash(source, text, workspace_id)
        image_paths_blob = ";".join(page_image_paths or [])
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
                "source": source,
                "filename": filename,
                "chunk_index": idx,
                "workspace_id": workspace_id,
                "parent_text": parent_text,
                "page_image_paths": image_paths_blob,
            }
            for idx, _ in enumerate(chunks)
        ]
        self.vectordb.upsert(
            ids=ids,
            embeddings=embeddings,
            documents=chunks,
            metadatas=metadatas,
            workspace_id=workspace_id,
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

    def list_workspaces(self) -> list[str]:
        workspaces = self.vectordb.list_workspaces()
        default_workspace = self.normalize_workspace_id(settings.default_workspace_id)
        if default_workspace not in workspaces:
            workspaces.insert(0, default_workspace)
        return sorted(set(workspaces))

    async def _retrieve_context(
        self,
        question: str,
        workspace_id: str | None = None,
    ) -> tuple[list[str], list[dict[str, object]], list[str], list[float]]:
        resolved_workspace = self.normalize_workspace_id(workspace_id)
        candidate_k = max(settings.top_k, settings.retrieval_candidate_k)
        queries = await self._expand_queries(question)
        merged_results: dict[str, tuple[str, dict[str, object], float]] = {}

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
                    "no_results_under_similarity_threshold",
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
    def _build_citations(metadatas: list[dict[str, object]], ids: list[str]) -> list[Citation]:
        citations: list[Citation] = []
        for idx, metadata in enumerate(metadatas):
            source = str(metadata.get("filename") or metadata.get("source") or "unknown")
            chunk_id = str(ids[idx]) if idx < len(ids) else "unknown"
            citations.append(Citation(source=source, chunk_id=chunk_id))
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
    ) -> tuple[AsyncIterator[str], list[Citation], int]:
        documents, metadatas, ids, _ = await self._retrieve_with_self_rag(question, workspace_id)

        if not documents:
            async def _fallback() -> AsyncIterator[str]:
                yield "I do not have enough information in the local knowledge base yet. Ingest documents first."

            return _fallback(), [], 0

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
        citations = self._build_citations(metadatas, ids)
        return stream, citations, len(documents)

    async def answer(
        self,
        question: str,
        history: list[ChatTurn] | None = None,
        system_prompt: str | None = None,
        workspace_id: str | None = None,
        llm_model: str | None = None,
    ) -> tuple[str, list[Citation], int]:
        documents, metadatas, ids, _ = await self._retrieve_with_self_rag(question, workspace_id)

        if not documents:
            logger.info("no_documents_from_vector_query", top_k=settings.top_k)
            return (
                "I do not have enough information in the local knowledge base yet. Ingest documents first.",
                [],
                0,
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
        citations = self._build_citations(metadatas, ids)
        return answer, citations, len(documents)
