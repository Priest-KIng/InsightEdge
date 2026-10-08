from app.services.rag import RAGService
from app.services.llm import LocalLLMService


def test_greeting_detection_is_specific() -> None:
    assert RAGService._is_greeting("hello")
    assert RAGService._is_greeting("good evening")
    assert not RAGService._is_greeting("hello document summary")


def test_meta_answer_reports_selected_model() -> None:
    answer = RAGService._meta_answer("what model are you using?", "phi3:mini")

    assert "phi3:mini" in answer


def test_explanation_prompt_asks_for_a_concise_complete_response() -> None:
    service = LocalLLMService("http://localhost:11434", "phi3:mini")

    prompt = service._build_prompt("Explain the process of electrolysis.", ["Water splits into hydrogen and oxygen."])

    assert "at most 120 words" in prompt
    assert "Use necessary steps or equations, then stop." in prompt


def test_factual_prompt_keeps_existing_answer_policy() -> None:
    service = LocalLLMService("http://localhost:11434", "phi3:mini")

    prompt = service._build_prompt("Where are the vectors stored?", ["Vectors are stored in ChromaDB."])

    assert "under 180 words" in prompt
