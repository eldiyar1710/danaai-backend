import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path

from docx import Document as DocxDocument
from pypdf import PdfReader

DOC_CONVERSION_TIMEOUT_SECONDS = 180

# Safety instructions rarely use Word heading styles; their sections look like
# "1. Общие требования безопасности" followed by items "1.1. ...". Only a top-level number
# followed by an upper-case word counts, and numbers must run in sequence, so numbered list
# items ("1. Наименование организации;") and quiz questions are not taken for headings.
_NUMBERED_HEADING = re.compile(r"^(\d{1,2})\.\s*([^\W\d_][^\n]{1,148})$")
_HEADING_MAX_CHARS = 150


class DocumentConversionError(ValueError):
    """A legacy document could not be converted to an extractable format."""


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
    if suffix == ".doc":
        return _parse_docx(convert_doc_to_docx(content))
    if suffix in {".txt", ".md"}:
        return _parse_text(content.decode("utf-8"), markdown=suffix == ".md")
    raise ValueError(f"Unsupported document suffix: {suffix}")


def _soffice_binary() -> str:
    for name in ("soffice", "libreoffice"):
        binary = shutil.which(name)
        if binary:
            return binary
    raise DocumentConversionError(
        "LibreOffice is required to process .doc files but is not installed in the worker"
    )


def convert_doc_to_docx(
    content: bytes, *, timeout_seconds: int = DOC_CONVERSION_TIMEOUT_SECONDS
) -> bytes:
    """Convert a Word 97-2003 document to DOCX with headless LibreOffice.

    Every call uses its own temporary LibreOffice profile so concurrent Celery tasks do not
    contend for the profile lock, and nothing is left on disk afterwards.
    """
    binary = _soffice_binary()
    with tempfile.TemporaryDirectory(prefix="semyzbay-doc-") as workdir:
        root = Path(workdir)
        source = root / "source.doc"
        source.write_bytes(content)
        output_dir = root / "out"
        command = [
            binary,
            f"-env:UserInstallation={(root / 'profile').as_uri()}",
            "--headless",
            "--norestore",
            "--convert-to",
            "docx",
            "--outdir",
            str(output_dir),
            str(source),
        ]
        try:
            subprocess.run(  # noqa: S603 - fixed argv, no shell, input is a temp file
                command,
                check=True,
                capture_output=True,
                timeout=timeout_seconds,
            )
        except subprocess.TimeoutExpired as exc:
            raise DocumentConversionError("DOC conversion timed out") from exc
        except subprocess.CalledProcessError as exc:
            raise DocumentConversionError("DOC conversion failed") from exc
        converted = output_dir / "source.docx"
        if not converted.is_file() or converted.stat().st_size == 0:
            raise DocumentConversionError("DOC conversion produced no output")
        return converted.read_bytes()


def _parse_pdf(content: bytes) -> list[ParsedBlock]:
    blocks: list[ParsedBlock] = []
    for page_number, page in enumerate(PdfReader(BytesIO(content)).pages, start=1):
        text = (page.extract_text() or "").strip()
        if text:
            blocks.append(ParsedBlock(text=text, page_number=page_number))
    if not blocks:
        raise ValueError("The PDF contains no extractable text")
    return blocks


def _numbered_heading(text: str, previous_number: int) -> tuple[int, str] | None:
    match = _NUMBERED_HEADING.match(text)
    if match is None or len(text) > _HEADING_MAX_CHARS:
        return None
    number, title = int(match.group(1)), match.group(2).strip()
    if not title[0].isupper() or title.endswith((";", ":", ",", "?")):
        return None
    if number != previous_number + 1:
        return None
    return number, title.rstrip(".")


def _parse_docx(content: bytes) -> list[ParsedBlock]:
    blocks: list[ParsedBlock] = []
    section: str | None = None
    section_number: str | None = None
    previous_number = 0
    for paragraph in DocxDocument(BytesIO(content)).paragraphs:
        text = paragraph.text.strip()
        if not text:
            continue
        style_name = paragraph.style.name if paragraph.style else None
        if style_name and style_name.lower().startswith("heading"):
            section = text
            section_number = None
            continue
        heading = _numbered_heading(text, previous_number)
        if heading is not None:
            previous_number, title = heading
            section = f"{previous_number}. {title}"
            section_number = str(previous_number)
            continue
        blocks.append(ParsedBlock(text=text, section_title=section, section_number=section_number))
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
