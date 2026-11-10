import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest

from app.modules.documents import parser
from app.modules.documents.parser import DocumentConversionError, parse_document

FIXTURE = Path(__file__).parent / "fixtures" / "sample_instruction.doc"
HAS_LIBREOFFICE = bool(shutil.which("soffice") or shutil.which("libreoffice"))


@pytest.mark.skipif(not HAS_LIBREOFFICE, reason="LibreOffice is not installed")
def test_legacy_doc_is_converted_and_parsed() -> None:
    blocks = parse_document("Инструкция №109.doc", FIXTURE.read_bytes())

    text = "\n".join(block.text for block in blocks)
    assert "страховочная привязь" in text
    assert "не моложе 18 лет" in text


def test_missing_libreoffice_reports_clear_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(parser.shutil, "which", lambda _name: None)

    with pytest.raises(DocumentConversionError, match="LibreOffice is required"):
        parse_document("manual.doc", FIXTURE.read_bytes())


def test_conversion_timeout_is_reported(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(parser.shutil, "which", lambda _name: "/usr/bin/soffice")

    def fake_run(*_args: Any, **kwargs: Any) -> None:
        raise subprocess.TimeoutExpired(cmd="soffice", timeout=kwargs["timeout"])

    monkeypatch.setattr(parser.subprocess, "run", fake_run)

    with pytest.raises(DocumentConversionError, match="timed out"):
        parser.convert_doc_to_docx(FIXTURE.read_bytes(), timeout_seconds=1)
