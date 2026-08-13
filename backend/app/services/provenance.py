from __future__ import annotations

from dataclasses import dataclass
import re

from app.config import settings

@dataclass(frozen=True)
class EvidenceAssessment:
    groundedness: float
    confidence: float
    supported_claims: int
    total_claims: int
    weak: bool
    reason: str


def assess_context(question: str, documents: list[str], distances: list[float] | None = None) -> EvidenceAssessment:
    if not documents:
        return EvidenceAssessment(0.0, 0.0, 0, 0, True, "No relevant chunks were retrieved from this workspace.")
    question_terms = _meaningful_terms(question)
    context_terms = set(_terms(" ".join(documents)))
    overlap = len(question_terms.intersection(context_terms)) / max(1, len(question_terms))
    best_score = max((1.0 / (1.0 + float(distance)) for distance in (distances or []) if distance is not None), default=0.0)
    groundedness = round(min(1.0, (0.7 * overlap) + (0.3 * best_score)), 3)
    weak = groundedness < settings.groundedness_min_score and not _overview_question(question)
    return EvidenceAssessment(
        groundedness=groundedness,
        confidence=round(groundedness, 3),
        supported_claims=1 if groundedness >= settings.groundedness_min_score else 0,
        total_claims=1,
        weak=weak,
        reason="Retrieved evidence overlaps the question." if not weak else "Retrieved evidence has weak lexical and relevance support.",
    )


def verify_answer(question: str, answer: str, documents: list[str]) -> EvidenceAssessment:
    claims = [part.strip() for part in re.split(r"(?<=[.!?])\s+", answer) if part.strip()]
    if not claims:
        return EvidenceAssessment(0.0, 0.0, 0, 0, True, "The local model returned no answer text.")
    context_terms = set(_terms(" ".join(documents)))
    supported = sum(1 for claim in claims if len(set(_meaningful_terms(claim)).intersection(context_terms)) >= 1)
    ratio = supported / len(claims)
    weak = ratio < settings.groundedness_min_score and not _overview_question(question)
    return EvidenceAssessment(
        groundedness=round(ratio, 3),
        confidence=round(ratio, 3),
        supported_claims=supported,
        total_claims=len(claims),
        weak=weak,
        reason="Answer claims overlap retrieved evidence." if not weak else "Some answer claims could not be matched to retrieved evidence.",
    )


def reinforce_exact_evidence(question: str, answer: str, documents: list[str]) -> str:
    """Preserve distinctive exact values when a small local model paraphrases them away."""
    lowered_question = question.lower()
    if not any(term in lowered_question for term in ("passphrase", "password", "code", "token", "exact phrase", "which phrase")):
        return answer
    context = "\n".join(documents)
    candidates = re.findall(r"\b[A-Za-z0-9]+(?:-[A-Za-z0-9]+){2,}\b", context)
    candidates.extend(re.findall(r'"([^"]{4,100})"', context))
    missing = [candidate.strip() for candidate in candidates if candidate.strip() and candidate.lower() not in answer.lower()]
    if not missing:
        return answer
    return answer.rstrip() + "\n\nExact evidence from the retrieved source: " + "; ".join(missing[:3]) + "."


def refusal_message(workspace_id: str, reason: str) -> str:
    return (
        f"I could not verify an answer from the relevant evidence in workspace `{workspace_id}`. "
        f"{reason} Please rephrase the question or inspect the available sources."
    )


def _terms(value: str) -> list[str]:
    return re.findall(r"[a-z0-9_]+", value.lower())


def _meaningful_terms(value: str) -> set[str]:
    return {term for term in _terms(value) if len(term) > 2 and term not in STOP_WORDS}


def _overview_question(question: str) -> bool:
    lowered = question.lower()
    return any(term in lowered for term in ("summarize", "summary", "overview", "what is in", "main themes"))


STOP_WORDS = {
    "the", "and", "for", "with", "from", "what", "where", "when", "which", "does", "this", "that", "are", "was", "were", "how", "why", "who", "can", "about", "into", "only", "does", "tell", "please",
}
