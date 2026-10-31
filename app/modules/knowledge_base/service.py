import asyncio
from collections.abc import Iterable
from uuid import UUID, uuid5

from fastapi import HTTPException
from qdrant_client import AsyncQdrantClient, models

from app.core.config import Settings
from app.modules.documents.embeddings import embed_dense, sparse_model
from app.modules.documents.indexer import DENSE_VECTOR, SPARSE_VECTOR
from app.modules.knowledge_base.schemas import (
    KnowledgeBaseStats,
    SearchHit,
    SearchRequest,
    SearchResponse,
)
from app.modules.users.models import User, UserRole


class KnowledgeBaseService:
    def __init__(self, settings: Settings, qdrant: AsyncQdrantClient) -> None:
        self.settings = settings
        self.qdrant = qdrant

    def tenant(self, actor: User, requested: UUID | None) -> UUID:
        if actor.role == UserRole.SUPER_ADMIN:
            if requested is None:
                raise HTTPException(status_code=422, detail="organization_id is required")
            return requested
        if actor.organization_id is None:
            raise HTTPException(status_code=403, detail="Tenant membership required")
        if requested is not None and requested != actor.organization_id:
            raise HTTPException(status_code=403, detail="Cross-tenant access denied")
        return actor.organization_id

    def active_filter(self, organization_id: UUID) -> models.Filter:
        return models.Filter(
            must=[
                models.FieldCondition(
                    key="organization_id",
                    match=models.MatchValue(value=str(organization_id)),
                ),
                models.FieldCondition(
                    key="approval_status", match=models.MatchValue(value="approved")
                ),
                models.FieldCondition(key="is_active", match=models.MatchValue(value="true")),
            ]
        )

    async def search(self, actor: User, request: SearchRequest) -> SearchResponse:
        organization_id = self.tenant(actor, request.organization_id)
        if not await self.qdrant.collection_exists(self.settings.qdrant_collection):
            return SearchResponse(results=[])
        dense, sparse = await asyncio.gather(
            embed_dense(self.settings, [request.query], query=True),
            asyncio.to_thread(
                lambda: next(
                    iter(
                        sparse_model(self.settings.sparse_embedding_model).query_embed(
                            request.query
                        )
                    )
                )
            ),
        )
        tenant_filter = self.active_filter(organization_id)
        response = await self.qdrant.query_points(
            collection_name=self.settings.qdrant_collection,
            prefetch=[
                models.Prefetch(
                    query=dense[0],
                    using=DENSE_VECTOR,
                    filter=tenant_filter,
                    limit=max(request.limit * 3, 20),
                ),
                models.Prefetch(
                    query=models.SparseVector(
                        indices=sparse.indices.tolist(), values=sparse.values.tolist()
                    ),
                    using=SPARSE_VECTOR,
                    filter=tenant_filter,
                    limit=max(request.limit * 3, 20),
                ),
            ],
            query=models.FusionQuery(fusion=models.Fusion.RRF),
            limit=request.limit,
            with_payload=True,
        )
        results: list[SearchHit] = []
        for point in response.points:
            payload = point.payload or {}
            results.append(
                SearchHit(
                    chunk_id=UUID(str(payload["chunk_id"])),
                    document_id=UUID(str(payload["document_id"])),
                    document_version_id=UUID(str(payload["document_version_id"])),
                    chunk_index=(
                        int(payload["chunk_index"])
                        if payload.get("chunk_index") is not None
                        else None
                    ),
                    text=str(payload["text"]),
                    score=point.score,
                    page_number=payload.get("page_number"),
                    section_title=payload.get("section_title"),
                    section_number=payload.get("section_number"),
                )
            )
        return SearchResponse(results=results)

    async def fetch_chunks(
        self,
        actor: User,
        organization_id: UUID | None,
        references: Iterable[tuple[UUID, int]],
    ) -> dict[tuple[UUID, int], SearchHit]:
        """Fetch deterministic neighboring chunks and re-check tenant/approval state."""
        tenant_id = self.tenant(actor, organization_id)
        requested = {(version_id, index) for version_id, index in references if index >= 0}
        if not requested or not await self.qdrant.collection_exists(
            self.settings.qdrant_collection
        ):
            return {}
        point_ids = [uuid5(version_id, str(index)) for version_id, index in requested]
        points = await self.qdrant.retrieve(
            collection_name=self.settings.qdrant_collection,
            ids=point_ids,
            with_payload=True,
            with_vectors=False,
        )
        chunks: dict[tuple[UUID, int], SearchHit] = {}
        for point in points:
            payload = point.payload or {}
            if (
                payload.get("organization_id") != str(tenant_id)
                or payload.get("approval_status") != "approved"
                or payload.get("is_active") != "true"
            ):
                continue
            version_id = UUID(str(payload["document_version_id"]))
            if payload.get("chunk_index") is None:
                continue
            chunk_index = int(payload["chunk_index"])
            key = (version_id, chunk_index)
            if key not in requested:
                continue
            chunks[key] = SearchHit(
                chunk_id=UUID(str(payload["chunk_id"])),
                document_id=UUID(str(payload["document_id"])),
                document_version_id=version_id,
                chunk_index=chunk_index,
                text=str(payload["text"]),
                score=0.0,
                page_number=payload.get("page_number"),
                section_title=payload.get("section_title"),
                section_number=payload.get("section_number"),
            )
        return chunks

    async def stats(self, actor: User, organization_id: UUID | None) -> KnowledgeBaseStats:
        tenant_id = self.tenant(actor, organization_id)
        if not await self.qdrant.collection_exists(self.settings.qdrant_collection):
            return KnowledgeBaseStats(organization_id=tenant_id, active_chunks=0)
        result = await self.qdrant.count(
            collection_name=self.settings.qdrant_collection,
            count_filter=self.active_filter(tenant_id),
            exact=True,
        )
        return KnowledgeBaseStats(organization_id=tenant_id, active_chunks=result.count)
