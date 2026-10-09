from fastapi import APIRouter, Depends, HTTPException, status
import time

from app.config import settings
from app.deps import require_admin, require_api_key
from app.schemas import (
    AuthConfigResponse,
    AuthLoginRequest,
    AuthSignupRequest,
    AuthTokenResponse,
    AuthUserRecord,
    AuthUserResponse,
    AuthUserStatusRequest,
    AuthUsersResponse,
)
from app.services.auth import AUTH_STORE, auth_is_configured, auth_is_requested, authenticate_user, issue_session_token

router = APIRouter(prefix="/auth", tags=["auth"])


@router.get("/config", response_model=AuthConfigResponse)
async def auth_config() -> AuthConfigResponse:
    if auth_is_requested() and not auth_is_configured():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Authentication is incompletely configured on this server",
        )
    enabled = auth_is_configured()
    return AuthConfigResponse(enabled=enabled, signup_enabled=enabled and settings.auth_allow_signup)


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
        role=str(AUTH_STORE.get_user(payload.username)["role"]),
    )


@router.post("/signup", response_model=AuthTokenResponse)
async def signup(payload: AuthSignupRequest) -> AuthTokenResponse:
    if not auth_is_configured() or not settings.auth_allow_signup:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Self sign-up is disabled")
    try:
        created = AUTH_STORE.create_user(payload.username, payload.password, role="user")
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    if not created:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Username is already in use")
    token, expires_at = issue_session_token(payload.username)
    return AuthTokenResponse(
        access_token=token,
        expires_in=max(1, expires_at - int(time.time())),
        username=payload.username,
        role="user",
    )


@router.get("/me", response_model=AuthUserResponse)
async def current_user(username: str | None = Depends(require_api_key)) -> AuthUserResponse:
    if not username:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User login is not enabled")
    user = AUTH_STORE.get_user(username)
    return AuthUserResponse(username=username, role=str(user["role"]) if user else "user")


@router.get("/users", response_model=AuthUsersResponse, dependencies=[Depends(require_admin)])
async def list_users() -> AuthUsersResponse:
    return AuthUsersResponse(users=[AuthUserRecord(**user) for user in AUTH_STORE.list_users()])


@router.post("/users", response_model=AuthUserRecord, status_code=status.HTTP_201_CREATED, dependencies=[Depends(require_admin)])
async def create_user(payload: AuthSignupRequest) -> AuthUserRecord:
    try:
        created = AUTH_STORE.create_user(payload.username, payload.password, role=payload.role)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    if not created:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Username is already in use")
    user = AUTH_STORE.get_user(payload.username)
    return AuthUserRecord(**user)


@router.patch("/users/{username}", response_model=AuthUserRecord, dependencies=[Depends(require_admin)])
async def set_user_status(username: str, payload: AuthUserStatusRequest) -> AuthUserRecord:
    try:
        updated = AUTH_STORE.set_active(username, payload.active)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    if not updated:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    user = AUTH_STORE.get_user(username)
    return AuthUserRecord(**user)
