from unittest.mock import AsyncMock, Mock

from app.core.health import check_dependencies


async def test_all_dependencies_are_reported_up() -> None:
    connection = AsyncMock()
    connection.execute = AsyncMock()
    context = AsyncMock()
    context.__aenter__.return_value = connection
    engine = Mock()
    engine.connect.return_value = context

    redis = AsyncMock()
    redis.ping.return_value = True
    qdrant = AsyncMock()
    qdrant.get_collections.return_value = []
    minio = Mock()
    minio.list_buckets.return_value = []

    result = await check_dependencies(
        engine=engine,
        redis=redis,
        qdrant=qdrant,
        minio=minio,
        timeout_seconds=1,
    )

    assert set(result) == {"postgres", "redis", "qdrant", "minio"}
    assert all(item["status"] == "up" for item in result.values())


async def test_failed_dependency_does_not_hide_other_results() -> None:
    engine = Mock()
    engine.connect.side_effect = ConnectionError
    redis = AsyncMock()
    redis.ping.return_value = True
    qdrant = AsyncMock()
    qdrant.get_collections.return_value = []
    minio = Mock()
    minio.list_buckets.return_value = []

    result = await check_dependencies(
        engine=engine,
        redis=redis,
        qdrant=qdrant,
        minio=minio,
        timeout_seconds=1,
    )

    assert result["postgres"] == {"status": "down", "detail": "ConnectionError"}
    assert result["redis"]["status"] == "up"
