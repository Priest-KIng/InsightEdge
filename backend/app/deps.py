from threading import Lock

from app.services.rag import RAGService
_RAG_SERVICE: RAGService | None = None
_RAG_LOCK = Lock()


def get_rag_service() -> RAGService:
    global _RAG_SERVICE
    if _RAG_SERVICE is not None:
        return _RAG_SERVICE

    with _RAG_LOCK:
        if _RAG_SERVICE is not None:
            return _RAG_SERVICE
        try:
            _RAG_SERVICE = RAGService()
        except Exception:
            _RAG_SERVICE = None
            raise
    return _RAG_SERVICE
