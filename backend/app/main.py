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

app = FastAPI(title=settings.app_name)
app.add_middleware(RequestContextMiddleware)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=settings.cors_allow_credentials,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health")
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

    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get(f"{settings.ollama_base_url.rstrip('/')}/api/tags")
            response.raise_for_status()
        components["ollama"] = {
            "status": "ok",
            "detail": f"Reachable at {settings.ollama_base_url}",
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
        "components": components,
    }


app.include_router(ingest_router, prefix=settings.api_prefix)
app.include_router(chat_router, prefix=settings.api_prefix)
