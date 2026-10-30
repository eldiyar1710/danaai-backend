import re
from dataclasses import dataclass

_INJECTION_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "instruction_override",
        re.compile(
            r"\b(?:ignore|disregard|forget)\s+(?:all\s+)?(?:previous|prior|above)\s+"
            r"(?:instructions?|rules?|prompts?)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "system_prompt_exfiltration",
        re.compile(
            r"\b(?:reveal|show|print|repeat)\s+(?:the\s+)?(?:system|developer)\s+prompt\b",
            re.IGNORECASE,
        ),
    ),
    (
        "russian_instruction_override",
        re.compile(
            r"\b(?:игнорируй|игнорировать|забудь)\s+(?:все\s+)?(?:предыдущие\s+)?"
            r"(?:инструкции|правила|указания)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "role_impersonation",
        re.compile(r"(?:^|\n)\s*(?:system|developer|assistant)\s*:\s*", re.IGNORECASE),
    ),
)


@dataclass(frozen=True)
class InjectionScan:
    suspicious: bool
    reasons: tuple[str, ...]


def scan_prompt_injection(text: str) -> InjectionScan:
    reasons = tuple(name for name, pattern in _INJECTION_PATTERNS if pattern.search(text))
    return InjectionScan(suspicious=bool(reasons), reasons=reasons)
