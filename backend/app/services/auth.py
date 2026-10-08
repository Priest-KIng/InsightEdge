from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time

from app.config import settings


def auth_is_configured() -> bool:
    return bool(
        settings.auth_username
        and settings.auth_password
        and settings.auth_signing_secret
        and len(settings.auth_signing_secret.encode("utf-8")) >= 32
    )


def auth_is_requested() -> bool:
    return bool(settings.auth_username or settings.auth_password or settings.auth_signing_secret)


def _encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def issue_session_token(username: str, now: int | None = None) -> tuple[str, int]:
    if not auth_is_configured():
        raise RuntimeError("Set AUTH_USERNAME, AUTH_PASSWORD, and AUTH_SIGNING_SECRET to enable login")
    issued_at = int(time.time()) if now is None else now
    expires_at = issued_at + max(1, settings.auth_session_minutes) * 60
    payload = _encode(json.dumps({"sub": username, "exp": expires_at}, separators=(",", ":")).encode())
    signing_input = f"v1.{payload}".encode("ascii")
    signature = hmac.new(settings.auth_signing_secret.encode(), signing_input, hashlib.sha256).digest()
    return f"v1.{payload}.{_encode(signature)}", expires_at


def verify_session_token(token: str, now: int | None = None) -> str | None:
    if not auth_is_configured():
        return None
    try:
        version, payload, signature = token.split(".")
        if version != "v1":
            return None
        signing_input = f"{version}.{payload}".encode("ascii")
        expected = _encode(hmac.new(settings.auth_signing_secret.encode(), signing_input, hashlib.sha256).digest())
        if not hmac.compare_digest(signature, expected):
            return None
        data = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
        username = data.get("sub")
        expires_at = int(data.get("exp", 0))
        current_time = int(time.time()) if now is None else now
        if username != settings.auth_username or expires_at <= current_time:
            return None
        return username
    except (ValueError, TypeError, AttributeError, json.JSONDecodeError):
        return None


def authenticate_user(username: str, password: str) -> bool:
    if not auth_is_configured():
        return False
    return hmac.compare_digest(username, settings.auth_username or "") and hmac.compare_digest(
        password,
        settings.auth_password or "",
    )
