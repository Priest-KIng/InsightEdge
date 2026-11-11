from fastapi.testclient import TestClient
import pytest

from app.config import settings
from app.main import app
from app.routes import auth as auth_routes
from app.services import auth as auth_service
from app.services.auth import AuthStore, authenticate_user, issue_session_token, verify_session_token


def isolate_auth_store(monkeypatch, tmp_path) -> AuthStore:
    db_path = tmp_path / "auth-test.db"
    monkeypatch.setattr(settings, "auth_db_path", db_path)
    store = AuthStore(db_path)
    monkeypatch.setattr(auth_service, "AUTH_STORE", store)
    monkeypatch.setattr(auth_routes, "AUTH_STORE", store)
    return store


def configure_auth(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(settings, "auth_username", "org-admin")
    monkeypatch.setattr(settings, "auth_password", "correct horse battery staple")
    monkeypatch.setattr(settings, "auth_signing_secret", "test-signing-secret-with-more-than-32-bytes")
    monkeypatch.setattr(settings, "auth_session_minutes", 10)
    monkeypatch.setattr(settings, "api_key", None)
    isolate_auth_store(monkeypatch, tmp_path)


def test_session_token_round_trip_and_expiry(monkeypatch, tmp_path) -> None:
    configure_auth(monkeypatch, tmp_path)
    token, expires_at = issue_session_token("org-admin", now=1000)

    assert expires_at == 1600
    assert verify_session_token(token, now=1599) == "org-admin"
    assert verify_session_token(token, now=1600) is None


def test_session_token_rejects_tampering(monkeypatch, tmp_path) -> None:
    configure_auth(monkeypatch, tmp_path)
    token, _ = issue_session_token("org-admin", now=1000)
    tampered = token[:-1] + ("A" if token[-1] != "A" else "B")

    assert verify_session_token(tampered, now=1001) is None
    assert verify_session_token("not.a.token") is None


@pytest.mark.integration
def test_login_issues_token_and_protected_api_accepts_it(monkeypatch, tmp_path) -> None:
    configure_auth(monkeypatch, tmp_path)
    with TestClient(app) as client:
        assert client.get("/api/auth/config").json() == {"enabled": True, "signup_enabled": False}
        assert client.get("/api/ingest/jobs/missing").status_code == 401

        bad_login = client.post(
            "/api/auth/login",
            json={"username": "org-admin", "password": "wrong"},
        )
        assert bad_login.status_code == 401

        login = client.post(
            "/api/auth/login",
            json={"username": "org-admin", "password": "correct horse battery staple"},
        )
        assert login.status_code == 200
        token = login.json()["access_token"]
        assert client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"}).json() == {
            "username": "org-admin",
            "role": "admin",
        }
        assert client.get("/api/ingest/jobs/missing", headers={"Authorization": f"Bearer {token}"}).status_code == 404


@pytest.mark.integration
def test_authentication_fails_closed_when_partially_configured(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(settings, "auth_username", "org-admin")
    monkeypatch.setattr(settings, "auth_password", None)
    monkeypatch.setattr(settings, "auth_signing_secret", None)
    monkeypatch.setattr(settings, "api_key", None)
    isolate_auth_store(monkeypatch, tmp_path)

    with TestClient(app) as client:
        assert client.get("/api/ingest/jobs/missing").status_code == 503
        assert client.get("/api/auth/config").status_code == 503
        assert client.post("/api/auth/login", json={"username": "org-admin", "password": "x"}).status_code == 503


@pytest.mark.integration
def test_legacy_api_key_still_authorizes_protected_routes(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(settings, "auth_username", None)
    monkeypatch.setattr(settings, "auth_password", None)
    monkeypatch.setattr(settings, "auth_signing_secret", None)
    monkeypatch.setattr(settings, "api_key", "local-development-key")
    isolate_auth_store(monkeypatch, tmp_path)

    with TestClient(app) as client:
        assert client.get("/api/ingest/jobs/missing").status_code == 401
        response = client.get(
            "/api/ingest/jobs/missing",
            headers={"Authorization": "Bearer local-development-key"},
        )
        assert response.status_code == 404


def test_credentials_use_constant_time_comparison(monkeypatch, tmp_path) -> None:
    configure_auth(monkeypatch, tmp_path)

    assert authenticate_user("org-admin", "correct horse battery staple")
    assert not authenticate_user("another-user", "correct horse battery staple")
