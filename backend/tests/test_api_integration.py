from collections.abc import AsyncIterator

from fastapi.testclient import TestClient
import pytest

from app.deps import get_rag_service
from app.main import _app as fastapi_app
from app.main import app
from app.schemas import Citation
from app.services.rag import RAGAnswer, RAGService


class FakeRAGService:
    @staticmethod
    def normalize_workspace_id(workspace_id):
        return RAGService.normalize_workspace_id(workspace_id)

    async def answer(self, question, history, system_prompt, workspace_id, llm_model):
        return RAGAnswer(
            answer="The pilot served 412 borrowers.",
            citations=[Citation(source="pilot.md", filename="pilot.md", chunk_id="doc:0", snippet="412 borrowers")],
            context_chunks=1,
            model="test-model",
            workspace_id=workspace_id,
            retrieval_mode="hybrid",
            retrieved_chunks=2,
            final_context_chunks=1,
            latency_ms=12.5,
            query_type="factual lookup",
            confidence=0.9,
            groundedness=0.9,
        )

    async def answer_stream(self, question, history, system_prompt, workspace_id, llm_model):
        async def tokens() -> AsyncIterator[str]:
            yield "The pilot "
            yield "served 412 borrowers."

        citations = [Citation(source="pilot.md", filename="pilot.md", chunk_id="doc:0", snippet="412 borrowers")]
        metadata = {
            "model": "test-model",
            "workspace_id": workspace_id,
            "retrieval_mode": "hybrid",
            "retrieved_chunks": 2,
            "final_context_chunks": 1,
            "query_type": "factual lookup",
            "confidence": 0.9,
            "groundedness": 0.9,
        }
        return tokens(), citations, 1, metadata


@pytest.mark.integration
def test_chat_json_api_serializes_answer_and_provenance() -> None:
    fastapi_app.dependency_overrides[get_rag_service] = FakeRAGService
    try:
        with TestClient(app) as client:
            response = client.post("/api/chat", json={"question": "How many borrowers?", "workspace_id": "org-a"})
        assert response.status_code == 200
        payload = response.json()
        assert payload["answer"] == "The pilot served 412 borrowers."
        assert payload["workspace_id"] == "org-a"
        assert payload["citations"][0]["filename"] == "pilot.md"
        assert payload["retrieved_chunks"] == 2
    finally:
        fastapi_app.dependency_overrides.clear()


@pytest.mark.integration
def test_stream_api_emits_tokens_and_final_metadata() -> None:
    fastapi_app.dependency_overrides[get_rag_service] = FakeRAGService
    try:
        with TestClient(app) as client:
            response = client.post("/api/chat/stream", json={"question": "How many borrowers?", "workspace_id": "org-a"})
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        assert '"type": "token"' in response.text
        assert '"type": "final"' in response.text
        assert '"filename": "pilot.md"' in response.text
        assert "The pilot served 412 borrowers." in response.text
    finally:
        fastapi_app.dependency_overrides.clear()


@pytest.mark.integration
def test_upload_api_rejects_unsupported_file_type() -> None:
    with TestClient(app) as client:
        response = client.post(
            "/api/ingest/files",
            data={"workspace_id": "org-a"},
            files={"files": ("payload.exe", b"not a document", "application/octet-stream")},
        )
    assert response.status_code == 400
    assert "Unsupported file type" in response.json()["detail"]
