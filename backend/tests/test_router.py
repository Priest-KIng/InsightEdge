import asyncio

from app.services.router import ModelRouter, classify_query


def test_query_classifier_is_deterministic_and_explainable() -> None:
    decision = classify_query("Compare the table values across documents")

    assert decision.query_type == "table/structured-data query"
    assert decision.retrieval_mode == "lexical"
    assert decision.complexity_score > 0
    assert decision.rationale


def test_model_router_falls_back_when_strong_model_is_missing(monkeypatch) -> None:
    router = ModelRouter("http://127.0.0.1:9", "phi3:mini")
    decision = classify_query("Compare the differences across documents")
    monkeypatch.setattr(router, "available_models", lambda: asyncio.sleep(0, result={"phi3:mini"}))

    selected = asyncio.run(router.select(decision))

    assert selected.model_name == "phi3:mini"
    assert "fallback" in selected.model_source


def test_heading_list_queries_use_structure_retrieval() -> None:
    decision = classify_query("Can you provide the list of headings in the document?")

    assert decision.query_type == "heading/list"
    assert decision.retrieval_mode == "lexical"
    assert decision.metadata_filter == {"block_type": "heading"}
    assert decision.final_top_k > decision.candidate_k // 3


def test_document_detail_queries_use_broad_context() -> None:
    decision = classify_query("Explain the document in detail")

    assert decision.query_type == "summarization"
    assert decision.retrieval_mode == "dense"
    assert decision.complexity_score >= 0.68
    assert decision.final_top_k >= 8
    assert "broader" in decision.rationale
