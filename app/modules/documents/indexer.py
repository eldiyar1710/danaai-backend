import asyncio
from collections.abc import Sequence
from uuid import UUID, uuid5

from qdrant_client import AsyncQdrantClient, models
from qdrant_client.http.exceptions import UnexpectedResponse

from app.core.config import Settings
from app.modules.documents.chunker import TextChunk
from app.modules.documents.embeddings import embed_dense, sparse_model
from app.modules.documents.models import Document

DENSE_VECTOR = "dense"
SPARSE_VECTOR = "sparse"


class DocumentIndexer:
    def __init__(
        self,
        settings: Settings,
        client: AsyncQdrantClient,
        *,
        initialize_models: bool = True,
    ) -> None:
        self.settings = settings
        self.client = client
        self._sparse = sparse_model(settings.sparse_embedding_model) if initialize_models else None

    async def ensure_collection(self) -> None:
        if await self.client.collection_exists(self.settings.qdrant_collection):
            return
        try:
            await self.client.create_collection(
                collection_name=self.settings.qdrant_collection,
                vectors_config={
                    DENSE_VECTOR: models.VectorParams(
                        size=self.settings.embedding_dimension, distance=models.Distance.COSINE
                    )
                },
                sparse_vectors_config={
                    SPARSE_VECTOR: models.SparseVectorParams(
                        index=models.SparseIndexParams(on_disk=False), modifier=models.Modifier.IDF
                    )
                },
            )
        except UnexpectedResponse:
            # Multiple workers may initialize a new blue-green collection concurrently.
            if not await self.client.collection_exists(self.settings.qdrant_collection):
                raise
        for field in (
            "organization_id",
            "document_id",
            "document_version_id",
            "approval_status",
            "is_active",
            "language",
        ):
            await self.client.create_payload_index(
                collection_name=self.settings.qdrant_collection,
                field_name=field,
                field_schema=models.PayloadSchemaType.KEYWORD,
            )

    async def replace_version(
        self,
        document: Document,
        version_id: UUID,
        chunks: Sequence[TextChunk],
        *,
        active: bool = False,
    ) -> list[UUID]:
        await self.ensure_collection()
        texts = [chunk.text for chunk in chunks]
        dense, sparse = await self.embed(texts)
        if len(dense) != len(chunks) or len(sparse) != len(chunks):
            raise RuntimeError("Embedding provider returned an unexpected vector count")
        point_ids = [uuid5(version_id, str(chunk.index)) for chunk in chunks]
        points = [
            models.PointStruct(
                id=point_id,
                vector={
                    DENSE_VECTOR: dense[index],
                    SPARSE_VECTOR: sparse[index],
                },
                payload={
                    "organization_id": str(document.organization_id),
                    "document_id": str(document.id),
                    "document_version_id": str(version_id),
                    "chunk_id": str(point_id),
                    "chunk_index": chunks[index].index,
                    "approval_status": "approved" if active else "pending",
                    "is_active": "true" if active else "false",
                    "language": document.language,
                    "page_number": chunks[index].page_number,
                    "section_title": chunks[index].section_title,
                    "section_number": chunks[index].section_number,
                    "text": chunks[index].text,
                },
            )
            for index, point_id in enumerate(point_ids)
        ]
        await self.client.upsert(
            collection_name=self.settings.qdrant_collection, points=points, wait=True
        )
        await self.client.delete(
            collection_name=self.settings.qdrant_collection,
            points_selector=models.FilterSelector(
                filter=models.Filter(
                    must=[
                        models.FieldCondition(
                            key="document_version_id",
                            match=models.MatchValue(value=str(version_id)),
                        )
                    ],
                    must_not=[models.HasIdCondition(has_id=point_ids)],
                )
            ),
            wait=True,
        )
        return point_ids

    async def embed(self, texts: list[str]) -> tuple[list[list[float]], list[models.SparseVector]]:
        if self._sparse is None:
            raise RuntimeError("Embedding models are not initialized")
        sparse_model_instance = self._sparse
        dense_raw, sparse_raw = await asyncio.gather(
            embed_dense(self.settings, texts),
            asyncio.to_thread(lambda: list(sparse_model_instance.embed(texts))),
        )
        return (
            dense_raw,
            [
                models.SparseVector(indices=vector.indices.tolist(), values=vector.values.tolist())
                for vector in sparse_raw
            ],
        )


async def set_version_active(
    client: AsyncQdrantClient, settings: Settings, version_id: UUID, *, active: bool
) -> None:
    if not await client.collection_exists(settings.qdrant_collection):
        return
    await client.set_payload(
        collection_name=settings.qdrant_collection,
        payload={
            "approval_status": "approved" if active else "archived",
            "is_active": "true" if active else "false",
        },
        points=models.Filter(
            must=[
                models.FieldCondition(
                    key="document_version_id",
                    match=models.MatchValue(value=str(version_id)),
                )
            ]
        ),
        wait=True,
    )


async def delete_document_points(
    client: AsyncQdrantClient, settings: Settings, document_id: UUID
) -> None:
    if not await client.collection_exists(settings.qdrant_collection):
        return
    await client.delete(
        collection_name=settings.qdrant_collection,
        points_selector=models.FilterSelector(
            filter=models.Filter(
                must=[
                    models.FieldCondition(
                        key="document_id",
                        match=models.MatchValue(value=str(document_id)),
                    )
                ]
            )
        ),
        wait=True,
    )
