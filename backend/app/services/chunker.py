from __future__ import annotations

import re


def chunk_text(text: str, chunk_size: int, chunk_overlap: int) -> list[str]:
    normalized_text = " ".join(text.split())
    if not normalized_text:
        return []

    if chunk_overlap >= chunk_size:
        raise ValueError("chunk_overlap must be smaller than chunk_size")

    sentences = re.split(r"(?<=[.!?])\s+", normalized_text)
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
