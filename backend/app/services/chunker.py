from __future__ import annotations

import re

from app.services.document_model import DocumentSegment, StructuredChunk

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


def chunk_structured_segments(
    segments: list[DocumentSegment],
    chunk_size: int,
    chunk_overlap: int,
) -> list[StructuredChunk]:
    """Chunk at structural boundaries and keep table blocks intact when possible."""
    if chunk_overlap >= chunk_size:
        raise ValueError("chunk_overlap must be smaller than chunk_size")

    chunks: list[StructuredChunk] = []
    for segment in segments:
        text = segment.text.strip()
        if not text:
            continue
        if segment.table_used:
            rows = [row.strip() for row in text.splitlines() if row.strip()]
            if len(text) <= chunk_size:
                parts = [text]
            else:
                parts = []
                header = rows[:2]
                current = list(header)
                for row in rows[2:] if len(rows) > 2 else rows:
                    candidate = "\n".join([*current, row])
                    if current and len(candidate) > chunk_size:
                        parts.append("\n".join(current))
                        current = list(header) + [row] if header else [row]
                    else:
                        current.append(row)
                if current:
                    parts.append("\n".join(current))
        else:
            parts = chunk_text(text, chunk_size, chunk_overlap)
        if not parts:
            continue
        cursor = segment.start_char or 0
        for part in parts:
            local_start = text.find(part)
            start = cursor + local_start if local_start >= 0 else segment.start_char
            end = start + len(part) if start is not None else segment.end_char
            chunks.append(
                StructuredChunk(
                    text=part,
                    block_type=segment.block_type,
                    section_title=segment.section_title,
                    page_number=segment.page_number,
                    slide_number=segment.slide_number,
                    start_char=start,
                    end_char=end,
                    ocr_used=segment.ocr_used,
                    table_used=segment.table_used,
                ),
            )
            if local_start >= 0:
                cursor = cursor + local_start + len(part)
    return chunks
