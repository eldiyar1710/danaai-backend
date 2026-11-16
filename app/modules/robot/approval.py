"""Explicit, checksum-bound approval of university PDF pages."""

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ApprovedDocument:
    sha256: str
    pages: frozenset[int]


def load_approvals(path: Path) -> dict[str, ApprovedDocument]:
    if not path.is_file():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or data.get("version") != 1:
        raise ValueError("Invalid robot approval manifest version")
    entries = data.get("documents")
    if not isinstance(entries, list):
        raise ValueError("Robot approval manifest needs a documents list")
    approved: dict[str, ApprovedDocument] = {}
    for entry in entries:
        if not isinstance(entry, dict):
            raise ValueError("Invalid robot approval entry")
        name = entry.get("file")
        digest = entry.get("sha256")
        pages = entry.get("pages")
        reviewer = entry.get("approved_by")
        date = entry.get("approved_at")
        if (
            not isinstance(name, str)
            or not name.endswith(".pdf")
            or Path(name).name != name
            or name in {"5.pdf", "Каталог знаний.pdf"}
            or not isinstance(digest, str)
            or len(digest) != 64
            or any(char not in "0123456789abcdef" for char in digest)
            or not isinstance(pages, list)
            or not pages
            or any(type(page) is not int or page < 1 for page in pages)
            or not isinstance(reviewer, str)
            or not reviewer.strip()
            or not isinstance(date, str)
            or not date.strip()
            or name in approved
        ):
            raise ValueError("Invalid robot approval entry")
        approved[name] = ApprovedDocument(digest, frozenset(pages))
    return approved


def verified_approval(path: Path, approval: ApprovedDocument) -> bool:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest() == approval.sha256
    except OSError:
        return False
