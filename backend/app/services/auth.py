from __future__ import annotations

import base64
import hashlib
import hmac
import json
import re
import secrets
import sqlite3
import time
from pathlib import Path

from app.config import settings

PASSWORD_ITERATIONS = 310_000
USERNAME_PATTERN = re.compile(r"^[A-Za-z0-9_.@-]{3,64}$")


class AuthStore:
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.execute("""CREATE TABLE IF NOT EXISTS users (
                username TEXT PRIMARY KEY COLLATE NOCASE,
                password_hash TEXT NOT NULL,
                role TEXT NOT NULL CHECK (role IN ('admin', 'user')),
                active INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )""")
        self._bootstrap_admin()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=10)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout = 5000")
        return conn

    @staticmethod
    def _hash_password(password: str, salt: bytes | None = None) -> str:
        actual_salt = salt or secrets.token_bytes(16)
        digest = hashlib.pbkdf2_hmac("sha256", password.encode(), actual_salt, PASSWORD_ITERATIONS)
        return f"pbkdf2_sha256${PASSWORD_ITERATIONS}${_encode(actual_salt)}${_encode(digest)}"

    @staticmethod
    def _verify_password(password: str, encoded: str) -> bool:
        try:
            algorithm, rounds, salt, expected = encoded.split("$")
            if algorithm != "pbkdf2_sha256":
                return False
            actual = AuthStore._hash_password(password, _decode(salt))
            return hmac.compare_digest(actual, encoded)
        except (ValueError, TypeError):
            return False

    def _bootstrap_admin(self) -> None:
        if not (settings.auth_username and settings.auth_password):
            return
        with self._connect() as conn:
            has_users = conn.execute("SELECT 1 FROM users LIMIT 1").fetchone()
            if not has_users:
                conn.execute(
                    "INSERT INTO users (username, password_hash, role) VALUES (?, ?, 'admin')",
                    (settings.auth_username, self._hash_password(settings.auth_password)),
                )

    def count(self) -> int:
        with self._connect() as conn:
            return int(conn.execute("SELECT COUNT(*) FROM users WHERE active = 1").fetchone()[0])

    def get_user(self, username: str) -> dict[str, object] | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT username, role, active, created_at FROM users WHERE username = ? COLLATE NOCASE",
                (username,),
            ).fetchone()
        return dict(row) if row else None

    def authenticate(self, username: str, password: str) -> bool:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT password_hash FROM users WHERE username = ? COLLATE NOCASE AND active = 1",
                (username,),
            ).fetchone()
        return bool(row and self._verify_password(password, row["password_hash"]))

    def create_user(self, username: str, password: str, role: str = "user") -> bool:
        _validate_credentials(username, password)
        try:
            with self._connect() as conn:
                conn.execute(
                    "INSERT INTO users (username, password_hash, role) VALUES (?, ?, ?)",
                    (username, self._hash_password(password), role),
                )
            return True
        except sqlite3.IntegrityError:
            return False

    def list_users(self) -> list[dict[str, object]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT username, role, active, created_at FROM users ORDER BY username COLLATE NOCASE"
            ).fetchall()
        return [dict(row) for row in rows]

    def set_active(self, username: str, active: bool) -> bool:
        with self._connect() as conn:
            user = conn.execute(
                "SELECT role, active FROM users WHERE username = ? COLLATE NOCASE", (username,)
            ).fetchone()
            if not user:
                return False
            if not active and user["role"] == "admin" and user["active"]:
                admins = conn.execute(
                    "SELECT COUNT(*) FROM users WHERE role = 'admin' AND active = 1"
                ).fetchone()[0]
                if admins <= 1:
                    raise ValueError("The last active administrator cannot be disabled")
            conn.execute(
                "UPDATE users SET active = ? WHERE username = ? COLLATE NOCASE",
                (int(active), username),
            )
            return True


def _validate_credentials(username: str, password: str) -> None:
    if not USERNAME_PATTERN.fullmatch(username):
        raise ValueError("Username must be 3–64 characters using letters, numbers, ., _, @, or -")
    if len(password) < 12:
        raise ValueError("Password must be at least 12 characters")
    if len(password) > 1024:
        raise ValueError("Password is too long")


def _encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


AUTH_STORE = AuthStore(settings.auth_db_path or settings.data_dir / "auth.db")


def auth_is_configured() -> bool:
    return bool(
        settings.auth_signing_secret
        and len(settings.auth_signing_secret.encode("utf-8")) >= 32
        and AUTH_STORE.count() > 0
    )


def auth_is_requested() -> bool:
    return bool(
        settings.auth_username
        or settings.auth_password
        or settings.auth_signing_secret
        or AUTH_STORE.count()
    )


def issue_session_token(username: str, now: int | None = None) -> tuple[str, int]:
    if not auth_is_configured():
        raise RuntimeError("Set AUTH_SIGNING_SECRET to enable login")
    user = AUTH_STORE.get_user(username)
    if not user or not user["active"]:
        raise RuntimeError("Cannot issue a session for an inactive user")
    issued_at = int(time.time()) if now is None else now
    expires_at = issued_at + max(1, settings.auth_session_minutes) * 60
    payload = _encode(json.dumps({"sub": user["username"], "exp": expires_at}, separators=(",", ":")).encode())
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
        data = json.loads(_decode(payload))
        username = data.get("sub")
        if int(data.get("exp", 0)) <= (int(time.time()) if now is None else now):
            return None
        user = AUTH_STORE.get_user(username)
        return str(user["username"]) if user and user["active"] else None
    except (ValueError, TypeError, AttributeError, json.JSONDecodeError):
        return None


def authenticate_user(username: str, password: str) -> bool:
    return bool(auth_is_configured() and AUTH_STORE.authenticate(username, password))
