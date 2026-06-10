from app.services.rag import RAGService


def test_greeting_detection_is_specific() -> None:
    assert RAGService._is_greeting("hello")
    assert RAGService._is_greeting("good evening")
    assert not RAGService._is_greeting("hello document summary")


def test_meta_answer_reports_selected_model() -> None:
    answer = RAGService._meta_answer("what model are you using?", "phi3:mini")

    assert "phi3:mini" in answer
