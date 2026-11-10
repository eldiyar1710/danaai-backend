# ruff: noqa: RUF001

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


def _docx(paragraphs: list[str]) -> bytes:
    from io import BytesIO

    from docx import Document

    document = Document()
    for text in paragraphs:
        document.add_paragraph(text)
    output = BytesIO()
    document.save(output)
    return output.getvalue()


def test_docx_numbered_sections_become_section_titles() -> None:
    blocks = parse_document(
        "instruction.docx",
        _docx(
            [
                "ИНСТРУКЦИЯ №90",
                "1. Общие требования безопасности",
                "1.1. К работе допускаются лица старше 18 лет.",
                "1. Наименование организации;",
                "2.Требования безопасности перед началом работы",
                "2.1. Проверить страховочную привязь.",
                "1. Чем измеряют давление?",
                "4. Пропущенный номер не является разделом",
            ]
        ),
    )

    sections = [(block.section_number, block.section_title, block.text) for block in blocks]
    assert sections[0] == (None, None, "ИНСТРУКЦИЯ №90")
    assert sections[1][:2] == ("1", "1. Общие требования безопасности")
    # A list item that restarts numbering stays body text of the current section.
    assert sections[2] == ("1", "1. Общие требования безопасности", "1. Наименование организации;")
    assert sections[3][:2] == ("2", "2. Требования безопасности перед началом работы")
    assert [text for _, _, text in sections[4:]] == [
        "1. Чем измеряют давление?",
        "4. Пропущенный номер не является разделом",
    ]


def test_paragraphs_of_one_section_are_merged_into_full_chunks() -> None:
    blocks = [
        ParsedBlock(text=f"- пункт {index} " + "слово " * 10, section_title="1. Общие")
        for index in range(30)
    ] + [ParsedBlock(text="2.1. Отдельный раздел.", section_title="2. Перед работой")]

    chunks = chunk_blocks(blocks, chunk_size=600, chunk_overlap=100)

    first_section = [chunk for chunk in chunks if chunk.section_title == "1. Общие"]
    assert len(first_section) < 10
    assert all(len(chunk.text) > 300 for chunk in first_section[:-1])
    # Chunks never cross a section boundary.
    assert chunks[-1].text == "2.1. Отдельный раздел."
    assert chunks[-1].section_title == "2. Перед работой"
