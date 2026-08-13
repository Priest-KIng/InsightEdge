from app.schemas import ChatResponse, Citation


def test_structured_citation_keeps_legacy_fields() -> None:
    citation = Citation(
        source="fixture.txt",
        chunk_id="fixture:0",
        document_id="doc-1",
        filename="fixture.txt",
        snippet="Local provenance snippet",
        score=0.91,
        retrieval_rank=1,
    )

    payload = citation.model_dump()
    assert payload["source"] == "fixture.txt"
    assert payload["chunk_id"] == "fixture:0"
    assert payload["document_id"] == "doc-1"
    assert payload["score"] == 0.91


def test_chat_response_supports_backward_compatible_metadata() -> None:
    response = ChatResponse(answer="ok", citations=[], context_chunks=0)

    assert response.answer == "ok"
    assert response.retrieval_mode == "hybrid"
    assert response.retrieved_chunks == 0
    assert response.final_context_chunks == 0
    assert response.refusal is False


def test_citation_serializes_structure_flags() -> None:
    citation = Citation(
        source="table.md",
        chunk_id="doc:1",
        table_used=True,
        block_type="table",
        slide_number=None,
    )

    payload = citation.model_dump()
    assert payload["table_used"] is True
    assert payload["block_type"] == "table"
