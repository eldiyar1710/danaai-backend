from dataclasses import dataclass
from io import BytesIO
from pathlib import Path

from docx import Document as DocxDocument
from pypdf import PdfReader


@dataclass(frozen=True, slots=True)
class ParsedBlock:
    text: str
    page_number: int | None = None
    section_title: str | None = None
    section_number: str | None = None


def parse_document(filename: str, content: bytes) -> list[ParsedBlock]:
    suffix = Path(filename).suffix.lower()
    if suffix == ".pdf":
        return _parse_pdf(content)
    if suffix == ".docx":
        return _parse_docx(content)
    if suffix in {".txt", ".md"}:
        return _parse_text(content.decode("utf-8"), markdown=suffix == ".md")
    raise ValueError(f"Unsupported document suffix: {suffix}")


def _parse_pdf(content: bytes) -> list[ParsedBlock]:
    blocks: list[ParsedBlock] = []
    for page_number, page in enumerate(PdfReader(BytesIO(content)).pages, start=1):
        text = (page.extract_text() or "").strip()
        if text:
            blocks.append(ParsedBlock(text=text, page_number=page_number))
    if not blocks:
        raise ValueError("The PDF contains no extractable text")
    return blocks


def _parse_docx(content: bytes) -> list[ParsedBlock]:
    blocks: list[ParsedBlock] = []
    section: str | None = None
    for paragraph in DocxDocument(BytesIO(content)).paragraphs:
        text = paragraph.text.strip()
        if not text:
            continue
        if paragraph.style and paragraph.style.name.lower().startswith("heading"):
            section = text
            continue
        blocks.append(ParsedBlock(text=text, section_title=section))
    if not blocks:
        raise ValueError("The DOCX contains no extractable text")
    return blocks


def _parse_text(text: str, *, markdown: bool) -> list[ParsedBlock]:
    blocks: list[ParsedBlock] = []
    section: str | None = None
    buffer: list[str] = []

    def flush() -> None:
        if buffer:
            blocks.append(ParsedBlock(text="\n".join(buffer), section_title=section))
            buffer.clear()

    for line in text.splitlines():
        stripped = line.strip()
        if markdown and stripped.startswith("#"):
            flush()
            section = stripped.lstrip("#").strip() or section
        elif stripped:
            buffer.append(stripped)
        else:
            flush()
    flush()
    if not blocks:
        raise ValueError("The document contains no text")
    return blocks
