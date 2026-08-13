from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class DocumentSegment:
    """A loader-level block whose structural provenance survives normalization."""

    text: str
    block_type: str = "paragraph"
    section_title: str | None = None
    page_number: int | None = None
    slide_number: int | None = None
    start_char: int | None = None
    end_char: int | None = None
    ocr_used: bool = False
    table_used: bool = False


@dataclass(frozen=True)
class StructuredChunk:
    text: str
    block_type: str
    section_title: str | None = None
    page_number: int | None = None
    slide_number: int | None = None
    start_char: int | None = None
    end_char: int | None = None
    ocr_used: bool = False
    table_used: bool = False

