from app.services.chunker import chunk_structured_segments
from app.services.document_model import DocumentSegment
from app.services.loader import _segment_text


def test_structure_parser_preserves_page_section_table_and_ocr() -> None:
    segments = _segment_text(
        "# Results\n\n[PAGE 2 OCR]\nScanned total: blue ledger total\n\n[PAGE 3 TABLE 1]\n| Name | Value |\n| A | 10 |",
        ".md",
    )

    assert any(segment.section_title == "Results" for segment in segments)
    assert any(segment.block_type == "heading" and segment.text == "Results" for segment in segments)
    assert any(segment.page_number == 2 and segment.ocr_used for segment in segments)
    assert any(segment.page_number == 3 and segment.table_used for segment in segments)


def test_structured_chunker_keeps_table_block_and_metadata() -> None:
    chunks = chunk_structured_segments(
        [
            DocumentSegment(
                text="| Name | Value |\n| A | 10 |",
                block_type="table",
                section_title="Results",
                page_number=3,
                start_char=20,
                end_char=46,
                table_used=True,
            ),
        ],
        chunk_size=100,
        chunk_overlap=10,
    )

    assert len(chunks) == 1
    assert chunks[0].table_used is True
    assert chunks[0].page_number == 3
    assert chunks[0].section_title == "Results"


def test_large_table_chunking_preserves_pipe_rows() -> None:
    rows = ["| Name | Value |", "| --- | --- |"] + [f"| Item {index} | {index} |" for index in range(20)]
    chunks = chunk_structured_segments(
        [DocumentSegment(text="\n".join(rows), block_type="table", table_used=True)],
        chunk_size=80,
        chunk_overlap=10,
    )

    assert len(chunks) > 1
    assert all("|" in chunk.text for chunk in chunks)


def test_heading_blocks_are_kept_separate_from_following_paragraph() -> None:
    segments = _segment_text(
        "# Introduction\nThis paragraph belongs to the introduction.\n\n## Method\nThe method text follows.",
        ".md",
    )

    heading_segments = [segment for segment in segments if segment.block_type == "heading"]
    assert [segment.text for segment in heading_segments] == ["Introduction", "Method"]
    assert all(segment.section_title for segment in heading_segments)
