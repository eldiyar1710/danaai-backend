from fastapi import HTTPException, status

from app.core.config import Settings
from app.modules.knowledge_base.schemas import SearchRequest
from app.modules.knowledge_base.service import KnowledgeBaseService
from app.modules.rag.context import build_context
from app.modules.rag.language import Language, detect_language, normalize_query
from app.modules.rag.reranker import RerankerProvider
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

    async def retrieve(self, actor: User, request: RAGRetrieveRequest) -> RAGRetrieveResponse:
        query = normalize_query(request.query)
        if len(query) < 2:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="Query is empty after normalization",
            )
        detected = detect_language(query, self.settings.default_language)
        response_language: Language = request.response_language or detected
        search = await self.knowledge_base.search(
            actor,
            SearchRequest(
                query=query,
                organization_id=request.organization_id,
                limit=self.settings.rag_retrieval_limit,
            ),
        )

        clean_hits = []
        excluded = 0
        for hit in search.results:
            scan = scan_prompt_injection(hit.text)
            if scan.suspicious and not self.settings.rag_allow_suspicious_context:
                excluded += 1
                continue
            clean_hits.append(hit)

        ranked = await self.reranker.rerank(query, clean_hits)
        context, sources = build_context(
            ranked[: self.settings.rag_rerank_limit],
            max_chunks=self.settings.rag_max_context_chunks,
            max_chars=self.settings.rag_max_context_chars,
            min_score=self.settings.rag_min_relevance_score,
        )
        warnings = []
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
