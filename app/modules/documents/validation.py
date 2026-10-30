from io import BytesIO
from pathlib import Path
from zipfile import BadZipFile, ZipFile

from fastapi import HTTPException

ALLOWED_SUFFIXES = {".pdf", ".docx", ".txt", ".md"}
MIME_BY_SUFFIX = {
    ".pdf": "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".txt": "text/plain",
    ".md": "text/markdown",
}


def validate_document(filename: str, content: bytes, declared_mime: str | None) -> str:
    suffix = Path(filename).suffix.lower()
    if suffix not in ALLOWED_SUFFIXES:
        raise HTTPException(status_code=415, detail="Supported formats: PDF, DOCX, TXT, MD")
    expected_mime = MIME_BY_SUFFIX[suffix]
    if declared_mime and declared_mime not in {expected_mime, "application/octet-stream"}:
        raise HTTPException(status_code=415, detail="File extension and MIME type do not match")
    if suffix == ".pdf" and not content.startswith(b"%PDF-"):
        raise HTTPException(status_code=422, detail="Invalid PDF content")
    if suffix == ".docx":
        try:
            with ZipFile(BytesIO(content)) as archive:
                names = set(archive.namelist())
        except BadZipFile as exc:
            raise HTTPException(status_code=422, detail="Invalid DOCX content") from exc
        if "[Content_Types].xml" not in names or "word/document.xml" not in names:
            raise HTTPException(status_code=422, detail="Invalid DOCX content")
    if suffix in {".txt", ".md"}:
        try:
            content.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise HTTPException(status_code=422, detail="Text documents must be UTF-8") from exc
    return expected_mime
