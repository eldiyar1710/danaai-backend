import unicodedata
from collections.abc import Sequence

from app.modules.rag.reranker import RankedHit
from app.modules.rag.schemas import RAGSource


def _deduplication_key(text: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", text).casefold().split())


def build_context(
    ranked_hits: Sequence[RankedHit], *, max_chunks: int, max_chars: int, min_score: float
) -> tuple[str, list[RAGSource]]:
    blocks: list[str] = []
    sources: list[RAGSource] = []
    seen: set[str] = set()
    used_chars = 0

    for ranked in ranked_hits:
        if ranked.score < min_score or len(sources) >= max_chunks:
            continue
        key = _deduplication_key(ranked.hit.text)
        if not key or key in seen:
            continue
        citation_id = f"S{len(sources) + 1}"
        location = []
        if ranked.hit.section_title:
            location.append(f"section={ranked.hit.section_title}")
        if ranked.hit.page_number is not None:
            location.append(f"page={ranked.hit.page_number}")
        metadata = f" ({', '.join(location)})" if location else ""
        prefix = f"[{citation_id}]{metadata}\n"
        remaining = max_chars - used_chars - len(prefix)
        if remaining <= 0:
            break
        text = ranked.hit.text[:remaining].strip()
        if not text:
            break
        block = f"{prefix}{text}"
        blocks.append(block)
        sources.append(
            RAGSource(
                citation_id=citation_id,
                chunk_id=ranked.hit.chunk_id,
                document_id=ranked.hit.document_id,
                document_version_id=ranked.hit.document_version_id,
                text=text,
                retrieval_score=ranked.hit.score,
                rerank_score=ranked.score,
                page_number=ranked.hit.page_number,
                section_title=ranked.hit.section_title,
                document_title=ranked.hit.document_title,
            )
        )
        seen.add(key)
        used_chars += len(block) + 2
        if len(text) < len(ranked.hit.text):
            break

    return "\n\n".join(blocks), sources
