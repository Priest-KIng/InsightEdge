from functools import lru_cache

from app.services.rag import RAGService


@lru_cache(maxsize=1)
def get_rag_service() -> RAGService:
    return RAGService()
