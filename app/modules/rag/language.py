import re
import unicodedata
from typing import Literal

Language = Literal["kk", "ru", "en"]

_CONTROL_CHARACTERS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_WHITESPACE = re.compile(r"\s+")
_CYRILLIC = re.compile(r"[А-Яа-яЁё]")  # noqa: RUF001
_KAZAKH_SPECIFIC = re.compile(r"[ӘәҒғҚқҢңӨөҰұҮүҺһІі]")


def normalize_query(query: str) -> str:
    """Normalize user input without translating or changing its meaning."""
    normalized = unicodedata.normalize("NFKC", query)
    normalized = _CONTROL_CHARACTERS.sub(" ", normalized)
    return _WHITESPACE.sub(" ", normalized).strip()


def detect_language(query: str, fallback: Language = "ru") -> Language:
    if _KAZAKH_SPECIFIC.search(query):
        return "kk"
    if _CYRILLIC.search(query):
        return "ru"
    if any(character.isalpha() for character in query):
        return "en"
    return fallback
