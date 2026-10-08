from app.services.provenance import (
    UNSUPPORTED_NUMERIC_REASON,
    assess_context,
    reinforce_exact_evidence,
    refusal_message,
    verify_answer,
)


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


def test_numeric_answer_must_be_present_in_retrieved_evidence() -> None:
    assessment = verify_answer(
        "By how much did literacy improve during the pilot?",
        "Literacy improved by 15%.",
        ["The pilot reported no measured change in literacy."],
    )

    assert assessment.weak is True
    assert assessment.reason == UNSUPPORTED_NUMERIC_REASON


def test_supported_numeric_answer_passes_verification() -> None:
    assessment = verify_answer(
        "How many unique borrowers were served?",
        "The pilot served 412 unique borrowers.",
        ["The pilot served 412 unique borrowers."],
    )

    assert assessment.weak is False


def test_comparison_cannot_add_an_unsupported_calculation() -> None:
    assessment = verify_answer(
        "Compare the solar array and battery with the daily service target.",
        "The battery stores 32 kWh. Energy required is 28.8 kWh, so it is sufficient.",
        ["The solar array is 4.8 kW. The battery stores 32 kWh. The daily service target is 6 hours."],
    )

    assert assessment.weak is True
    assert assessment.reason == UNSUPPORTED_NUMERIC_REASON
