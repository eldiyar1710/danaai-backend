from uuid import uuid4

from qdrant_client import AsyncQdrantClient, models

from app.core.config import Settings
from app.modules.documents.chunker import TextChunk
from app.modules.documents.indexer import (
    DocumentIndexer,
    delete_document_points,
    set_version_active,
)
from app.modules.documents.models import ApprovalStatus, Document, DocumentStatus
from app.modules.knowledge_base.service import KnowledgeBaseService
from app.modules.users.models import User, UserRole


class FakeIndexer(DocumentIndexer):
    async def embed(self, texts: list[str]) -> tuple[list[list[float]], list[models.SparseVector]]:
        return (
            [[1.0, 0.0, float(index)] for index, _ in enumerate(texts)],
            [models.SparseVector(indices=[index], values=[1.0]) for index, _ in enumerate(texts)],
        )


async def test_replace_and_activate_version_in_qdrant() -> None:
    settings = Settings(embedding_dimension=3, qdrant_collection="test_documents")
    client = AsyncQdrantClient(location=":memory:")
    document = Document(
        id=uuid4(),
        organization_id=uuid4(),
        uploaded_by=uuid4(),
        title="Safety",
        original_filename="safety.txt",
        minio_path="private/safety.txt",
        mime_type="text/plain",
        size_bytes=10,
        language="en",
        status=DocumentStatus.PROCESSING,
        approval_status=ApprovalStatus.PENDING,
        active_version_id=None,
    )
    version_id = uuid4()
    chunks = [
        TextChunk(0, "Lock equipment.", 1, "Isolation", None),
        TextChunk(1, "Check guards.", 2, "Restart", None),
    ]
    assert DocumentIndexer.embedding_text(document.title, chunks[0]) == (
        "Safety\nIsolation\nLock equipment."
    )
    try:
        point_ids = await FakeIndexer(settings, client, initialize_models=False).replace_version(
            document, version_id, chunks
        )
        assert len(point_ids) == 2
        points = await client.retrieve(
            settings.qdrant_collection, ids=point_ids, with_payload=True, with_vectors=True
        )
        assert len(points) == 2
        assert points[0].payload is not None
        assert points[0].payload["is_active"] == "false"

        await set_version_active(client, settings, version_id, active=True)
        active = await client.count(
            settings.qdrant_collection,
            count_filter=models.Filter(
                must=[models.FieldCondition(key="is_active", match=models.MatchValue(value="true"))]
            ),
            exact=True,
        )
        assert active.count == 2

        actor = User(
            id=uuid4(),
            organization_id=document.organization_id,
            email="admin@example.com",
            hashed_password="not-used",
            first_name="Test",
            last_name="Admin",
            role=UserRole.ORG_ADMIN,
            is_active=True,
        )
        fetched = await KnowledgeBaseService(settings, client).fetch_chunks(
            actor,
            None,
            {(version_id, 0), (version_id, 1), (version_id, 99)},
        )
        assert set(fetched) == {(version_id, 0), (version_id, 1)}
        assert fetched[(version_id, 1)].text == "Check guards."
        actor.organization_id = uuid4()
        assert not await KnowledgeBaseService(settings, client).fetch_chunks(
            actor, None, {(version_id, 0)}
        )

        replacement_ids = await FakeIndexer(
            settings, client, initialize_models=False
        ).replace_version(document, version_id, chunks[:1], active=True)
        assert replacement_ids == point_ids[:1]
        after_reindex = await client.count(
            settings.qdrant_collection,
            count_filter=models.Filter(
                must=[
                    models.FieldCondition(
                        key="document_version_id",
                        match=models.MatchValue(value=str(version_id)),
                    )
                ]
            ),
            exact=True,
        )
        assert after_reindex.count == 1

        result = await client.query_points(
            settings.qdrant_collection,
            prefetch=[
                models.Prefetch(query=[1.0, 0.0, 0.0], using="dense", limit=5),
                models.Prefetch(
                    query=models.SparseVector(indices=[0], values=[1.0]),
                    using="sparse",
                    limit=5,
                ),
            ],
            query=models.FusionQuery(fusion=models.Fusion.RRF),
            query_filter=models.Filter(
                must=[
                    models.FieldCondition(
                        key="organization_id",
                        match=models.MatchValue(value=str(document.organization_id)),
                    ),
                    models.FieldCondition(
                        key="approval_status",
                        match=models.MatchValue(value="approved"),
                    ),
                    models.FieldCondition(key="is_active", match=models.MatchValue(value="true")),
                ]
            ),
            limit=5,
        )
        assert result.points
        assert str(result.points[0].id) == str(point_ids[0])

        await delete_document_points(client, settings, document.id)
        assert (await client.count(settings.qdrant_collection, exact=True)).count == 0
    finally:
        await client.close()
