from app.services.provenance import assess_context, reinforce_exact_evidence, refusal_message, verify_answer


def test_weak_context_is_refused_with_workspace_traceability() -> None:
    assessment = assess_context("What is the lunar export protocol?", ["A local storage note."], [1.0])

    assert assessment.weak is True
    assert "workspace-1" in refusal_message("workspace-1", assessment.reason)


def test_supported_answer_receives_groundedness_signal() -> None:
    assessment = verify_answer(
        "Where are vectors stored?",
        "Vectors are stored in ChromaDB.",
        ["Documents are stored in a local ChromaDB vector store."],
    )

    assert assessment.groundedness > 0
    assert assessment.weak is False


def test_exact_evidence_is_reinserted_when_local_model_paraphrases_it() -> None:
    answer = reinforce_exact_evidence(
        "What is the audit passphrase?",
        "The document says a passphrase exists.",
        ["The audit passphrase is cobalt-lantern-4729."],
    )

    assert "cobalt-lantern-4729" in answer
