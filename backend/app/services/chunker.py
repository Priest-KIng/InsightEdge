from __future__ import annotations

import re


ABBREVIATION_PATTERN = re.compile(
    r"\b(?:Mr|Mrs|Ms|Dr|Prof|Sr|Jr|St|vs|etc|e\.g|i\.e|U\.S|U\.K|U\.N)\.",
    flags=re.IGNORECASE,
)
ACRONYM_PATTERN = re.compile(r"\b(?:[A-Za-z]\.){2,}")
DOT_TOKEN = "<DOT>"


def _protect_sentence_dots(text: str) -> str:
    def _replace_dots(match: re.Match[str]) -> str:
        return match.group(0).replace(".", DOT_TOKEN)

    text = ABBREVIATION_PATTERN.sub(_replace_dots, text)
    text = ACRONYM_PATTERN.sub(_replace_dots, text)
    return text


def _restore_sentence_dots(text: str) -> str:
    return text.replace(DOT_TOKEN, ".")


def chunk_text(text: str, chunk_size: int, chunk_overlap: int) -> list[str]:
    normalized_text = " ".join(text.split())
    if not normalized_text:
        return []

    if chunk_overlap >= chunk_size:
        raise ValueError("chunk_overlap must be smaller than chunk_size")

    protected_text = _protect_sentence_dots(normalized_text)
    sentences = [_restore_sentence_dots(item) for item in re.split(r"(?<=[.!?])\s+", protected_text)]
    normalized_sentences: list[str] = []
    for sentence in sentences:
        sentence = sentence.strip()
        if not sentence:
            continue
        if len(sentence) <= chunk_size:
            normalized_sentences.append(sentence)
            continue
        for start in range(0, len(sentence), chunk_size):
            part = sentence[start : start + chunk_size].strip()
            if part:
                normalized_sentences.append(part)
    chunks: list[str] = []
    current_chunk = ""
    for sentence in normalized_sentences:

        if current_chunk and len(current_chunk) + 1 + len(sentence) > chunk_size:
            chunks.append(current_chunk.strip())
            if chunk_overlap > 0:
                current_chunk = current_chunk[-chunk_overlap:]
            else:
                current_chunk = ""

        if current_chunk:
            current_chunk = f"{current_chunk} {sentence}".strip()
        else:
            current_chunk = sentence

    if current_chunk.strip():
        chunks.append(current_chunk.strip())

    return chunks
