# ruff: noqa: RUF001
import re
from collections import Counter
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from app.modules.documents.chunker import chunk_blocks
from app.modules.documents.parser import parse_document

_WORD = re.compile(r"[0-9A-Za-z\u0400-\u04FF]{3,}")
_STOPWORDS = {
    "and",
    "the",
    "для",
    "как",
    "что",
    "это",
    "или",
    "при",
    "его",
    "её",
    "она",
    "они",
    "меня",
    "можно",
    "нужно",
    "есть",
    "был",
    "была",
    "были",
    "под",
    "над",
    "без",
    "про",
}
_PROJECT_ROOT = Path(__file__).resolve().parents[3]


@dataclass(frozen=True, slots=True)
class Passage:
    file_name: str
    page: int
    text: str

    @property
    def label(self) -> str:
        note = " устаревший документ." if self.file_name == "5.pdf" else ""
        return f"{self.file_name}, страница {self.page}.{note}"


class UniversityKnowledge:
    def __init__(self, passages: list[Passage]) -> None:
        self.passages = passages
        self._stems = [set(_tokens(passage.text)) for passage in passages]
        counts: Counter[str] = Counter()
        for stems in self._stems:
            counts.update(stems)
        self._document_frequency = counts

    def search(self, question: str, limit: int = 6) -> list[Passage]:
        tokens = set(_tokens(question))
        if not tokens or not self.passages:
            return []
        scored: list[tuple[float, int, Passage]] = []
        for index, (passage, stems) in enumerate(zip(self.passages, self._stems, strict=True)):
            overlap = tokens & stems
            if not overlap:
                continue
            score = sum(1 / (1 + self._document_frequency[token]) for token in overlap)
            scored.append((score, -index, passage))
        scored.sort(reverse=True)
        return [passage for _, _, passage in scored[:limit]]


def _tokens(text: str) -> list[str]:
    words = [word.casefold().replace("ё", "е") for word in _WORD.findall(text)]
    useful = [word for word in words if word not in _STOPWORDS]
    return [_stem(word) for word in (useful or words)]


def _stem(word: str) -> str:
    if len(word) >= 6:
        return word[:5]
    return word


def resolve_knowledge_dir(directory: str) -> Path:
    path = Path(directory)
    if path.is_absolute():
        return path
    rooted = _PROJECT_ROOT / path
    if rooted.is_dir():
        return rooted
    return path


def load_knowledge(directory: Path, *, chunk_size: int, chunk_overlap: int) -> UniversityKnowledge:
    passages: list[Passage] = []
    if directory.is_dir():
        for path in sorted(directory.glob("*.pdf")):
            passages.extend(_passages_from_pdf(path, chunk_size, chunk_overlap))
    return UniversityKnowledge(passages)


@lru_cache(maxsize=1)
def cached_knowledge(directory: str, chunk_size: int, chunk_overlap: int) -> UniversityKnowledge:
    return load_knowledge(
        resolve_knowledge_dir(directory), chunk_size=chunk_size, chunk_overlap=chunk_overlap
    )


def _passages_from_pdf(path: Path, chunk_size: int, chunk_overlap: int) -> list[Passage]:
    try:
        blocks = parse_document(path.name, path.read_bytes())
        chunks = chunk_blocks(blocks, chunk_size=chunk_size, chunk_overlap=chunk_overlap)
    except (OSError, ValueError):
        return []
    return [
        Passage(file_name=path.name, page=chunk.page_number or 1, text=chunk.text)
        for chunk in chunks
    ]
