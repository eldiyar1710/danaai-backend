import asyncio
from dataclasses import asdict, dataclass
from typing import Any, Literal

from minio import Minio
from qdrant_client import AsyncQdrantClient
from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine


@dataclass(frozen=True, slots=True)
class DependencyHealth:
    status: Literal["up", "down"]
    detail: str | None = None


async def _check_database(engine: AsyncEngine) -> None:
    async with engine.connect() as connection:
        await connection.execute(text("SELECT 1"))


async def _check_redis(client: Redis) -> None:
    if not await client.ping():
        raise RuntimeError("Redis PING returned false")


async def _check_qdrant(client: AsyncQdrantClient) -> None:
    await client.get_collections()


async def _check_minio(client: Minio) -> None:
    await asyncio.to_thread(client.list_buckets)


async def check_dependencies(
    *,
    engine: AsyncEngine,
    redis: Redis,
    qdrant: AsyncQdrantClient,
    minio: Minio,
    timeout_seconds: float,
) -> dict[str, dict[str, Any]]:
    checks = {
        "postgres": _check_database(engine),
        "redis": _check_redis(redis),
        "qdrant": _check_qdrant(qdrant),
        "minio": _check_minio(minio),
    }

    async def run(coroutine: Any) -> DependencyHealth:
        try:
            await asyncio.wait_for(coroutine, timeout=timeout_seconds)
        except Exception as exc:
            return DependencyHealth(status="down", detail=type(exc).__name__)
        return DependencyHealth(status="up")

    results = await asyncio.gather(*(run(check) for check in checks.values()))
    return {name: asdict(result) for name, result in zip(checks, results, strict=True)}
