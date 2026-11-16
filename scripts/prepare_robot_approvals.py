"""Prepare PDF hashes and page counts for a human document review."""

import hashlib
import json
from pathlib import Path

from pypdf import PdfReader

from app.core.config import get_settings
from app.modules.robot.knowledge import resolve_project_path


def main() -> None:
    directory = resolve_project_path(get_settings().knowledge_dir)
    documents = []
    for path in sorted(directory.glob("*.pdf")):
        if path.name in {"5.pdf", "Каталог знаний.pdf"}:
            continue
        documents.append(
            {
                "file": path.name,
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                "page_count": len(PdfReader(path).pages),
                "proposed_pages": [],
                "review_status": "pending",
            }
        )
    output = Path("robot-approval-candidates.json")
    output.write_text(
        json.dumps({"version": 1, "documents": documents}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"Prepared {len(documents)} candidates in {output}")


if __name__ == "__main__":
    main()
