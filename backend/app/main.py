from __future__ import annotations

import asyncio

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import httpx

from app.config import settings
from app.deps import get_rag_service
from app.logging_setup import RequestContextMiddleware, configure_logging
from app.routes.chat import router as chat_router
from app.routes.ingest import router as ingest_router

configure_logging()

_app = FastAPI(title=settings.app_name)
_app.add_middleware(RequestContextMiddleware)


async def _fetch_ollama_models() -> list[str]:
    async with httpx.AsyncClient(timeout=5.0) as client:
        response = await client.get(f"{settings.ollama_base_url.rstrip('/')}/api/tags")
        response.raise_for_status()
    data = response.json()
    models = data.get("models", [])
    if not isinstance(models, list):
        return []
    return [
        model_name
        for item in models
        if isinstance(item, dict)
        for model_name in [str(item.get("name") or item.get("model") or "").strip()]
        if model_name
    ]


@_app.get("/api/health")
async def health() -> dict[str, object]:
    components: dict[str, dict[str, str]] = {
        "embedding": {
            "status": "degraded",
            "detail": "Embedding service not initialized",
        },
        "ollama": {
            "status": "degraded",
            "detail": "Ollama API unreachable",
        },
    }

    try:
        rag_service = await asyncio.to_thread(get_rag_service)
        embedder = getattr(rag_service, "embedder", None)
        embedding_model = getattr(embedder, "model", None)
        if embedding_model is not None:
            components["embedding"] = {
                "status": "ok",
                "detail": f"Loaded provider={settings.embedding_provider} model={settings.embedding_model}",
            }
        else:
            components["embedding"] = {
                "status": "degraded",
                "detail": "Embedding model object is missing",
            }
    except Exception as exc:
        components["embedding"] = {
            "status": "degraded",
            "detail": f"Embedding init failed: {exc}",
        }

    available_llm_models: list[str] = []
    try:
        available_llm_models = await _fetch_ollama_models()
        if settings.llm_model not in available_llm_models:
            installed = ", ".join(available_llm_models) if available_llm_models else "none"
            raise RuntimeError(f"Configured model {settings.llm_model!r} is not installed; available: {installed}")
        components["ollama"] = {
            "status": "ok",
            "detail": f"Reachable at {settings.ollama_base_url}; default model {settings.llm_model} is installed",
        }
    except Exception as exc:
        components["ollama"] = {
            "status": "degraded",
            "detail": f"Ollama check failed: {exc}",
        }

    overall_ok = all(item.get("status") == "ok" for item in components.values())
    return {
        "status": "ok" if overall_ok else "degraded",
        "app": settings.app_name,
        "embedding_model": settings.embedding_model,
        "llm_model": settings.llm_model,
        "available_llm_models": available_llm_models,
        "components": components,
    }


_app.include_router(ingest_router, prefix=settings.api_prefix)
_app.include_router(chat_router, prefix=settings.api_prefix)

app = CORSMiddleware(
    _app,
    allow_origins=settings.cors_origins,
    allow_credentials=settings.cors_allow_credentials,
    allow_methods=["*"],
    allow_headers=["*"],
)
