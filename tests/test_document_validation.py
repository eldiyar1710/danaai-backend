from io import BytesIO
from zipfile import ZipFile

import pytest
from fastapi import HTTPException

from app.modules.documents.validation import validate_document


def test_accepts_pdf_signature() -> None:
    assert validate_document("manual.pdf", b"%PDF-1.7\ncontent", "application/pdf") == (
        "application/pdf"
    )


def test_rejects_fake_pdf() -> None:
    with pytest.raises(HTTPException) as error:
        validate_document("manual.pdf", b"not a pdf", "application/pdf")
    assert error.value.status_code == 422


def test_accepts_minimal_docx_container() -> None:
    output = BytesIO()
    with ZipFile(output, "w") as archive:
        archive.writestr("[Content_Types].xml", "<Types />")
        archive.writestr("word/document.xml", "<document />")
    assert validate_document(
        "manual.docx",
        output.getvalue(),
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ).endswith("wordprocessingml.document")


def test_rejects_non_utf8_text() -> None:
    with pytest.raises(HTTPException) as error:
        validate_document("manual.txt", b"\xff", "text/plain")
    assert error.value.status_code == 422
