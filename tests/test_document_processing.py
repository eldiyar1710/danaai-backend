from app.modules.documents.chunker import chunk_blocks
from app.modules.documents.parser import ParsedBlock, parse_document


def test_markdown_parser_preserves_sections() -> None:
    blocks = parse_document(
        "manual.md", b"# Isolation\nLock the equipment.\n\n# Restart\nCheck the guard."
    )
    assert [block.section_title for block in blocks] == ["Isolation", "Restart"]
    assert blocks[0].text == "Lock the equipment."


def test_chunker_preserves_metadata_and_overlap() -> None:
    chunks = chunk_blocks(
        [ParsedBlock(text="word " * 100, page_number=7, section_title="Safety")],
        chunk_size=100,
        chunk_overlap=20,
    )
    assert len(chunks) > 1
    assert [chunk.index for chunk in chunks] == list(range(len(chunks)))
    assert all(chunk.page_number == 7 for chunk in chunks)
    assert all(chunk.section_title == "Safety" for chunk in chunks)


def test_text_parser_rejects_empty_document() -> None:
    try:
        parse_document("empty.txt", b"\n\n")
    except ValueError as error:
        assert "no text" in str(error)
    else:
        raise AssertionError("empty document must be rejected")
