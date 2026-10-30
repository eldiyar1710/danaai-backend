import asyncio
import math
import re
from collections.abc import Sequence
from dataclasses import dataclass
from functools import lru_cache
from typing import Protocol

from app.core.config import Settings
from app.modules.knowledge_base.schemas import SearchHit

_TOKEN = re.compile(r"[^\W_]+", re.UNICODE)


@dataclass(frozen=True)
class RankedHit:
    hit: SearchHit
    score: float


class RerankerProvider(Protocol):
    async def rerank(self, query: str, hits: Sequence[SearchHit]) -> list[RankedHit]: ...


def _tokens(text: str) -> set[str]:
    return {token.casefold() for token in _TOKEN.findall(text)}


class LexicalReranker:
    """Deterministic lightweight fallback combining RRF and lexical coverage."""

    async def rerank(self, query: str, hits: Sequence[SearchHit]) -> list[RankedHit]:
        query_tokens = _tokens(query)
        ranked: list[RankedHit] = []
        for hit in hits:
            document_tokens = _tokens(hit.text)
            overlap = (
                len(query_tokens & document_tokens) / len(query_tokens) if query_tokens else 0.0
            )
            retrieval = max(0.0, min(float(hit.score), 1.0))
            ranked.append(RankedHit(hit=hit, score=(0.65 * retrieval) + (0.35 * overlap)))
        return sorted(ranked, key=lambda item: item.score, reverse=True)


@lru_cache(maxsize=2)
def _cross_encoder(model_name: str) -> object:
    from fastembed.rerank.cross_encoder import TextCrossEncoder

    return TextCrossEncoder(model_name=model_name, lazy_load=True)


class FastEmbedReranker:
    def __init__(self, model_name: str) -> None:
        self.model_name = model_name

    def _score(self, query: str, hits: Sequence[SearchHit]) -> list[float]:
        model = _cross_encoder(self.model_name)
        raw_scores = model.rerank(query, [hit.text for hit in hits])  # type: ignore[attr-defined]
        return [
            1.0 / (1.0 + math.exp(-max(-30.0, min(float(score), 30.0)))) for score in raw_scores
        ]

    async def rerank(self, query: str, hits: Sequence[SearchHit]) -> list[RankedHit]:
        if not hits:
            return []
        semantic_scores = await asyncio.to_thread(self._score, query, hits)
        ranked = [
            RankedHit(
                hit=hit,
                score=(0.2 * max(0.0, min(float(hit.score), 1.0))) + (0.8 * semantic_score),
            )
            for hit, semantic_score in zip(hits, semantic_scores, strict=True)
        ]
        return sorted(ranked, key=lambda item: item.score, reverse=True)


def create_reranker(settings: Settings) -> RerankerProvider:
    if settings.reranker_provider == "fastembed":
        return FastEmbedReranker(settings.reranker_model)
    return LexicalReranker()
