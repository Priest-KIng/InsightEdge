from threading import Lock
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.config import settings

from app.services.rag import RAGService
_RAG_SERVICE: RAGService | None = None
_RAG_LOCK = Lock()
_BEARER = HTTPBearer(auto_error=False)


def require_api_key(credentials: HTTPAuthorizationCredentials | None = Depends(_BEARER)) -> None:
    if not settings.api_key:
        return
    if credentials is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing bearer token")
    if credentials.scheme.lower() != "bearer" or credentials.credentials != settings.api_key:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid bearer token")


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
