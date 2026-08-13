from __future__ import annotations

from dataclasses import dataclass
import re
import time

import httpx
import structlog

from app.config import settings

logger = structlog.get_logger(__name__)


@dataclass(frozen=True)
class RoutingDecision:
    query_type: str
    complexity_score: float
    rationale: str
    retrieval_mode: str
    candidate_k: int
    final_top_k: int
    metadata_filter: dict[str, object] | None = None
    use_compression: bool = False
    use_reranking: bool = False
    use_hyde: bool = False
    use_multi_query: bool = False
    use_parent_document: bool = False
    model_name: str = ""
    model_source: str = "default"
    num_gpu: int | None = None

    def as_metadata(self) -> dict[str, object]:
        return {
            "query_type": self.query_type,
            "complexity_score": self.complexity_score,
            "routing_rationale": self.rationale,
            "retrieval_mode": self.retrieval_mode,
            "candidate_k": self.candidate_k,
            "final_top_k": self.final_top_k,
            "model": self.model_name,
            "model_source": self.model_source,
            "num_gpu": self.num_gpu,
        }


def classify_query(question: str) -> RoutingDecision:
    normalized = " ".join(question.lower().split())
    tokens = set(re.findall(r"[a-z0-9_]+", normalized))

    if normalized in {"hi", "hello", "hey", "good morning", "good afternoon", "good evening"}:
        return _decision("greeting/meta", 0.02, "Greeting detected; retrieval is unnecessary.", "none", 0)
    if (
        normalized in {"who are you", "what can you do", "what model", "which model"}
        or "what model are you using" in normalized
        or "which model are you using" in normalized
    ):
        return _decision("greeting/meta", 0.04, "Assistant capability question detected; retrieval is unnecessary.", "none", 0)
    if len(tokens) <= 2 or any(token in tokens for token in {"this", "that", "it", "they"}) and len(tokens) <= 5:
        return _decision("ambiguous/underspecified", 0.32, "The question is short or referential and may need clarification.", "hybrid", 12)

    if tokens.intersection({"heading", "headings", "header", "headers", "section", "sections", "outline"}):
        return _decision(
            "heading/list",
            0.38,
            "The user requested document structure; retrieve heading blocks and return an exact list.",
            "lexical",
            64,
            final_top_k=32,
            metadata_filter={"block_type": "heading"},
        )
    if tokens.intersection({"ocr", "scanned", "scan", "image", "handwritten", "recognition"}):
        return _decision(
            "OCR/scanned-document query",
            0.56,
            "OCR or scanned-document terms detected; prioritize OCR-marked chunks.",
            "hybrid",
            16,
            metadata_filter={"ocr_used": True},
            use_compression=True,
        )
    if tokens.intersection({"table", "row", "column", "sheet", "spreadsheet", "cell", "csv"}):
        return _decision(
            "table/structured-data query",
            0.52,
            "Table or structured-data terms detected; prioritize table chunks and lexical matching.",
            "lexical",
            16,
            metadata_filter={"table_used": True},
        )
    if any(term in normalized for term in ("across documents", "multiple documents", "all documents", "both documents")):
        return _decision(
            "multi-document synthesis",
            0.82,
            "The question explicitly spans multiple documents.",
            "hybrid_rerank",
            24,
            use_compression=True,
            use_reranking=True,
            use_multi_query=True,
            use_parent_document=True,
        )
    if tokens.intersection({"compare", "comparison", "contrast", "versus", "vs", "difference", "similar"}):
        return _decision(
            "compare/contrast",
            0.72,
            "Comparison language detected; retrieve a wider multi-document candidate set.",
            "hybrid_rerank",
            24,
            use_compression=True,
            use_reranking=True,
            use_multi_query=True,
        )
    if (
        tokens.intersection({"summarize", "summary", "overview", "main", "key", "themes"})
        or (
            tokens.intersection({"explain", "detail", "detailed", "thorough", "walkthrough", "describe"})
            and tokens.intersection({"document", "documents", "file", "content", "paper", "report"})
        )
    ):
        return _decision(
            "summarization",
            0.72 if tokens.intersection({"detail", "detailed", "thorough", "walkthrough"}) else 0.62,
            "Document overview/detail intent detected; retrieve a broader representative context.",
            "dense",
            24,
            final_top_k=8,
            use_compression=True,
        )
    return _decision(
        "factual lookup",
        min(0.48, 0.18 + (0.04 * max(0, len(tokens) - 5))),
        "A concrete document fact is requested; combine lexical and dense evidence.",
        "hybrid",
        12,
    )


def _decision(
    query_type: str,
    complexity_score: float,
    rationale: str,
    retrieval_mode: str,
    candidate_k: int,
    *,
    metadata_filter: dict[str, object] | None = None,
    final_top_k: int | None = None,
    use_compression: bool = False,
    use_reranking: bool = False,
    use_hyde: bool | None = None,
    use_multi_query: bool = False,
    use_parent_document: bool = False,
) -> RoutingDecision:
    return RoutingDecision(
        query_type=query_type,
        complexity_score=round(max(0.0, min(1.0, complexity_score)), 3),
        rationale=rationale,
        retrieval_mode=retrieval_mode,
        candidate_k=max(0, candidate_k),
        final_top_k=max(0, final_top_k if final_top_k is not None else (settings.top_k if candidate_k else 0)),
        metadata_filter=metadata_filter,
        use_compression=use_compression,
        use_reranking=use_reranking,
        use_hyde=settings.enable_hyde if use_hyde is None else use_hyde,
        use_multi_query=use_multi_query or settings.enable_multi_query,
        use_parent_document=use_parent_document or settings.enable_parent_document_retrieval,
    )


class ModelRouter:
    def __init__(self, base_url: str, default_model: str) -> None:
        self.base_url = base_url.rstrip("/")
        self.default_model = default_model
        self._cached_models: tuple[float, set[str]] | None = None

    async def available_models(self) -> set[str]:
        now = time.monotonic()
        if self._cached_models and now - self._cached_models[0] < 30:
            return set(self._cached_models[1])
        try:
            async with httpx.AsyncClient(timeout=3.0) as client:
                response = await client.get(f"{self.base_url}/api/tags")
                response.raise_for_status()
            models = {
                str(item.get("name") or item.get("model") or "").strip()
                for item in response.json().get("models", [])
                if isinstance(item, dict)
            }
            models.discard("")
        except Exception as exc:
            logger.warning("model_catalog_unavailable", error=str(exc))
            models = {self.default_model}
        self._cached_models = (now, models)
        return set(models)

    async def select(
        self,
        decision: RoutingDecision,
        manual_model: str | None = None,
    ) -> RoutingDecision:
        if manual_model and manual_model.strip():
            selected = manual_model.strip()
            gpu = settings.router_strong_num_gpu if selected == settings.router_strong_model else settings.llm_num_gpu
            return RoutingDecision(
                **{
                    **decision.__dict__,
                    "model_name": selected,
                    "model_source": "manual",
                    "num_gpu": gpu,
                },
            )
        if not settings.enable_model_router or decision.query_type == "greeting/meta":
            return RoutingDecision(**{**decision.__dict__, "model_name": self.default_model, "model_source": "default"})

        available = await self.available_models()
        if decision.complexity_score >= 0.68:
            preferred = settings.router_strong_model
            source = "complexity-strong"
            gpu = settings.router_strong_num_gpu
        elif decision.complexity_score >= 0.45:
            preferred = settings.router_balanced_model
            source = "complexity-balanced"
            gpu = settings.llm_num_gpu
        else:
            preferred = settings.router_simple_model
            source = "complexity-simple"
            gpu = settings.llm_num_gpu
        selected = preferred if preferred in available else self.default_model
        if selected != preferred:
            source = f"{source}-fallback"
            gpu = settings.llm_num_gpu
        return RoutingDecision(**{**decision.__dict__, "model_name": selected, "model_source": source, "num_gpu": gpu})
