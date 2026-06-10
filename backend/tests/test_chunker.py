from app.services.chunker import chunk_text


def test_chunk_text_preserves_abbreviations_and_overlap() -> None:
    chunks = chunk_text(
        "Dr. Ada wrote the local RAG note. It explains SQLite state and ChromaDB vectors.",
        chunk_size=45,
        chunk_overlap=8,
    )

    assert chunks
    assert "Dr. Ada" in chunks[0]
    assert any("SQLite" in chunk for chunk in chunks)


def test_chunk_overlap_must_be_smaller_than_chunk_size() -> None:
    try:
        chunk_text("sample", chunk_size=10, chunk_overlap=10)
    except ValueError as exc:
        assert "chunk_overlap" in str(exc)
    else:
        raise AssertionError("Expected ValueError for invalid overlap")
