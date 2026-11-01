import asyncio
from uuid import UUID

from fastapi import HTTPException, status

from app.core.config import Settings
from app.modules.knowledge_base.schemas import SearchHit, SearchRequest
from app.modules.knowledge_base.service import KnowledgeBaseService
from app.modules.rag.context import build_context
from app.modules.rag.language import Language, detect_language, normalize_query
from app.modules.rag.query_expansion import QueryExpander
from app.modules.rag.reranker import RankedHit, RerankerProvider
from app.modules.rag.schemas import RAGRetrieveRequest, RAGRetrieveResponse
from app.modules.rag.security import scan_prompt_injection
from app.modules.users.models import User


class RAGService:
    def __init__(
        self,
        settings: Settings,
        knowledge_base: KnowledgeBaseService,
        reranker: RerankerProvider,
    ) -> None:
        self.settings = settings
        self.knowledge_base = knowledge_base
        self.reranker = reranker
        self.query_expander = QueryExpander(settings)

    async def _expand_neighbors(
        self,
        actor: User,
        request: RAGRetrieveRequest,
        ranked: list[RankedHit],
    ) -> tuple[list[RankedHit], int]:
        eligible = [
            item for item in ranked if item.score >= self.settings.rag_min_relevance_score
        ][: self.settings.rag_seed_limit]
        window = self.settings.rag_neighbor_window
        if not eligible or window == 0:
            return eligible, 0
        references = {
            (item.hit.document_version_id, item.hit.chunk_index + offset)
            for item in eligible
            for offset in range(-window, window + 1)
            if item.hit.chunk_index is not None and item.hit.chunk_index + offset >= 0
        }
        fetched = await self.knowledge_base.fetch_chunks(
            actor, request.organization_id, references
        )
        expanded: list[RankedHit] = []
        seen: set[tuple[object, int]] = set()
        excluded = 0
        for seed in eligible:
            if seed.hit.chunk_index is None:
                expanded.append(seed)
                continue
            for offset in range(-window, window + 1):
                index = seed.hit.chunk_index + offset
                if index < 0:
                    continue
                key = (seed.hit.document_version_id, index)
                if key in seen:
                    continue
                candidate = seed.hit if offset == 0 else fetched.get(key)
                if candidate is None:
                    continue
                scan = scan_prompt_injection(candidate.text)
                if scan.suspicious and not self.settings.rag_allow_suspicious_context:
                    excluded += 1
                    continue
                if offset:
                    candidate = candidate.model_copy(
                        update={"score": max(seed.hit.score * 0.95, 0.0)}
                    )
                expanded.append(
                    RankedHit(
                        candidate,
                        seed.score if offset == 0 else max(seed.score * 0.95, 0.0),
                    )
                )
                seen.add(key)
        return expanded, excluded

    async def retrieve(self, actor: User, request: RAGRetrieveRequest) -> RAGRetrieveResponse:
        query = normalize_query(request.query)
        if len(query) < 2:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="Query is empty after normalization",
            )
        detected = detect_language(query, self.settings.default_language)
        response_language: Language = request.response_language or detected
        expansion = await self.query_expander.expand(query, detected)
        searches = await asyncio.gather(
            *(
                self.knowledge_base.search(
                    actor,
                    SearchRequest(
                        query=retrieval_query,
                        organization_id=request.organization_id,
                        limit=self.settings.rag_retrieval_limit,
                    ),
                )
                for retrieval_query in expansion.queries
            )
        )

        merged_hits: dict[UUID, SearchHit] = {}
        for search in searches:
            for hit in search.results:
                existing = merged_hits.get(hit.chunk_id)
                if existing is None or hit.score > existing.score:
                    merged_hits[hit.chunk_id] = hit
        search_hits = sorted(
            merged_hits.values(), key=lambda item: item.score, reverse=True
        )[: self.settings.rag_retrieval_limit]

        clean_hits = []
        excluded = 0
        for hit in search_hits:
            scan = scan_prompt_injection(hit.text)
            if scan.suspicious and not self.settings.rag_allow_suspicious_context:
                excluded += 1
                continue
            clean_hits.append(hit)

        ranked = await self.reranker.rerank(query, clean_hits)
        expanded, neighbor_excluded = await self._expand_neighbors(actor, request, ranked)
        excluded += neighbor_excluded
        context, sources = build_context(
            expanded,
            max_chunks=self.settings.rag_max_context_chunks,
            max_chars=self.settings.rag_max_context_chars,
            min_score=self.settings.rag_min_relevance_score,
        )
        warnings = [expansion.warning] if expansion.warning else []
        if excluded:
            warnings.append("Suspicious retrieved content was excluded from the model context")
        if not sources:
            warnings.append("No approved active source met the relevance and safety thresholds")
        return RAGRetrieveResponse(
            normalized_query=query,
            detected_language=detected,
            response_language=response_language,
            insufficient_context=not sources,
            context=context,
            sources=sources,
            excluded_suspicious_chunks=excluded,
            warnings=warnings,
        )
