import asyncio

from app.services.router import ModelRouter, classify_query, is_multi_source_query


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


def test_generic_and_british_english_document_requests_route_to_summaries() -> None:
    for question in (
        "summarise the document",
        "Hello there can you help me what the document says",
        "Can you tell me what these documents are about?",
        "What do all the reports contain?",
    ):
        decision = classify_query(question)
        assert decision.query_type == "summarization"
        assert decision.final_top_k >= 6


def test_topic_specific_document_question_stays_factual() -> None:
    decision = classify_query("What does the document say about annual operating cost?")

    assert decision.query_type == "factual lookup"


def test_multi_source_intent_covers_aggregate_and_version_comparisons() -> None:
    assert is_multi_source_query("Summarize the main themes across all documents")
    assert is_multi_source_query("For extraction, what percentage is it compared to the earlier result?")
    assert is_multi_source_query("How many incident postmortems describe automatic fallback?")
    assert not is_multi_source_query("What is the maximum upload size?")


def test_long_compound_question_routes_for_cross_source_coverage() -> None:
    question = (
        "For the Proxima Bank priority routing rollout, what caused the throttling and "
        "what temporary policy exception did we apply, and how do we verify it is not "
        "burning the enterprise route SLOs?"
    )

    assert is_multi_source_query(question)
    assert not is_multi_source_query("What is the maximum upload size and how is it configured?")
