from threading import Lock
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.config import settings
from app.services.auth import AUTH_STORE, auth_is_configured, auth_is_requested, verify_session_token

from app.services.rag import RAGService
_RAG_SERVICE: RAGService | None = None
_RAG_LOCK = Lock()
_BEARER = HTTPBearer(auto_error=False)


def require_api_key(credentials: HTTPAuthorizationCredentials | None = Depends(_BEARER)) -> str | None:
    if not settings.api_key and not auth_is_requested():
        return
    if auth_is_requested() and not auth_is_configured():
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Authentication is incompletely configured")
    if credentials is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing bearer token")
    if credentials.scheme.lower() != "bearer":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid bearer token")
    # A shared development API key must not bypass member disablement when
    # organization accounts are enabled.
    if settings.api_key and not auth_is_configured() and credentials.credentials == settings.api_key:
        return settings.auth_username
    username = verify_session_token(credentials.credentials)
    if username is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired bearer token")
    return username


def require_admin(username: str | None = Depends(require_api_key)) -> str:
    user = AUTH_STORE.get_user(username) if username else None
    if not user or not user["active"] or user["role"] != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Administrator access required")
    return str(user["username"])


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
