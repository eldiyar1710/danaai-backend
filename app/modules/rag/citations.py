import re
from collections.abc import Sequence

from app.modules.rag.schemas import CitationValidation, RAGSource

_CITATION = re.compile(r"\[S([1-9][0-9]*)\]")


def validate_citations(
    answer: str, sources: Sequence[RAGSource], *, require_citation: bool = True
) -> CitationValidation:
    available = {source.citation_id for source in sources}
    citations = list(dict.fromkeys(f"S{match}" for match in _CITATION.findall(answer)))
    unknown = [citation for citation in citations if citation not in available]
    missing = require_citation and bool(answer.strip()) and bool(sources) and not citations
    return CitationValidation(
        valid=not unknown and not missing,
        citations=citations,
        unknown_citations=unknown,
        missing_citations=missing,
    )
