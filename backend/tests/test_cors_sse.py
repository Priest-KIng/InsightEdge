from fastapi.testclient import TestClient

from app.main import app


def test_frontend_origin_is_allowed_for_stream_endpoint() -> None:
    client = TestClient(app)

    response = client.options(
        "/api/chat/stream",
        headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type",
        },
    )

    assert response.status_code == 200
    assert response.headers.get("access-control-allow-origin") == "http://localhost:5173"
