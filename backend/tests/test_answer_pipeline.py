from __future__ import annotations

import asyncio
from types import SimpleNamespace

from app.schemas import Citation
from app.services.provenance import EvidenceAssessment
from app.services.rag import RAGService
from app.services.router import classify_query


def test_non_stream_answer_collects_the_shared_scoped_stream_pipeline() -> None:
    service = RAGService.__new__(RAGService)
    service.llm = SimpleNamespace(model_name="phi3:mini")
    calls = []

    async def token_stream():
        yield "A scoped "
        yield "answer."

    async def answer_stream(question, history, system_prompt, workspace_id, llm_model):
        calls.append((question, workspace_id, llm_model))
        return (
            token_stream(),
            [Citation(source="river.txt", filename="river.txt", chunk_id="river:0")],
            1,
            {
                "model": "phi3:mini",
                "workspace_id": "research",
                "retrieval_mode": "dense",
                "retrieved_chunks": 1,
                "final_context_chunks": 1,
                "latency_ms": 25.0,
                "query_type": "summarization",
                "complexity_score": 0.62,
                "routing_rationale": "Explicit source scope.",
                "confidence": 0.9,
                "groundedness": 1.0,
                "refusal": False,
                "candidate_chunks": 1,
                "verification_reason": "Supported by the selected source.",
            },
        )

    service._answer_stream_routed = answer_stream
    answer = asyncio.run(
        service._answer_routed(
            "Summarize river.txt",
            history=[],
            system_prompt=None,
            workspace_id="research",
            llm_model="phi3:mini",
        ),
    )

    assert calls == [("Summarize river.txt", "research", "phi3:mini")]
    assert answer.answer == "A scoped answer."
    assert [citation.filename for citation in answer.citations] == ["river.txt"]
    assert answer.retrieved_chunks == answer.final_context_chunks == 1
    assert answer.query_type == "summarization"
    assert answer.refusal is False


def test_json_and_sse_keep_retrieved_evidence_inside_resolved_document_scope() -> None:
    service = RAGService.__new__(RAGService)
    service.llm = SimpleNamespace(model_name="phi3:mini")
    base_decision = classify_query("What reserve coefficient is reported in river.txt?")
    decision = base_decision.__class__(
        **{**base_decision.__dict__, "model_name": "phi3:mini"},
    )

    async def route_question(question, manual_model):
        return decision

    async def resolve_document_scope(question, workspace_id, history):
        return (
            {"document_id": "river-id"},
            [{"doc_id": "river-id", "source": "river.txt"}],
            "named document",
            [
                {"doc_id": "river-id", "source": "river.txt"},
                {"doc_id": "harbor-id", "source": "harbor.txt"},
            ],
        )

    async def retrieval(question, workspace_id, routed_decision):
        assert routed_decision.metadata_filter == {"document_id": "river-id"}
        # Simulate a store returning a near-duplicate despite its metadata filter.
        return (
            ["River reserve coefficient is 1.10.", "Harbor reserve coefficient is 2.30."],
            [
                {"document_id": "river-id", "filename": "river.txt"},
                {"document_id": "harbor-id", "filename": "harbor.txt"},
            ],
            ["river:0", "harbor:0"],
            [0.1, 0.2],
        )

    async def generate_stream(*args, **kwargs):
        yield "River reserve coefficient is 1.10."

    service._route_question = route_question
    service._resolve_document_scope = resolve_document_scope
    service._retrieve_with_self_rag = retrieval
    service._weak_evidence_assessment = lambda *args: EvidenceAssessment(
        groundedness=1.0,
        confidence=1.0,
        supported_claims=1,
        total_claims=1,
        weak=False,
        reason="Supported by the selected source.",
    )
    service.llm.generate_stream = generate_stream

    async def exercise_both_paths():
        json_answer = await service.answer("What reserve coefficient is reported in river.txt?", workspace_id="research")
        stream, stream_citations, _, metadata = await service.answer_stream(
            "What reserve coefficient is reported in river.txt?",
            workspace_id="research",
        )
        stream_answer = "".join([part async for part in stream])
        return json_answer, stream_answer, stream_citations, metadata

    json_answer, stream_answer, stream_citations, metadata = asyncio.run(exercise_both_paths())

    assert json_answer.answer == stream_answer == "River reserve coefficient is 1.10."
    assert [citation.filename for citation in json_answer.citations] == ["river.txt"]
    assert [citation.filename for citation in stream_citations] == ["river.txt"]
    assert json_answer.candidate_chunks == metadata["candidate_chunks"] == 1
