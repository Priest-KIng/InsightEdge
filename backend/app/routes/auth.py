from fastapi import APIRouter, Depends, HTTPException, status
import time

from app.deps import require_api_key
from app.schemas import AuthConfigResponse, AuthLoginRequest, AuthTokenResponse, AuthUserResponse
from app.services.auth import auth_is_configured, auth_is_requested, authenticate_user, issue_session_token

router = APIRouter(prefix="/auth", tags=["auth"])


@router.get("/config", response_model=AuthConfigResponse)
async def auth_config() -> AuthConfigResponse:
    if auth_is_requested() and not auth_is_configured():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Authentication is incompletely configured on this server",
        )
    return AuthConfigResponse(enabled=auth_is_configured())


@router.post("/login", response_model=AuthTokenResponse)
async def login(payload: AuthLoginRequest) -> AuthTokenResponse:
    if not auth_is_configured():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Authentication is not fully configured on this server",
        )
    if not authenticate_user(payload.username, payload.password):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Incorrect username or password")
    token, expires_at = issue_session_token(payload.username)
    return AuthTokenResponse(
        access_token=token,
        expires_in=max(1, expires_at - int(time.time())),
        username=payload.username,
    )


@router.get("/me", response_model=AuthUserResponse)
async def current_user(username: str | None = Depends(require_api_key)) -> AuthUserResponse:
    if not username:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User login is not enabled")
    return AuthUserResponse(username=username)
