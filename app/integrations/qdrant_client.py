from math import ceil

from qdrant_client import AsyncQdrantClient

from app.core.config import Settings


def create_qdrant_client(settings: Settings) -> AsyncQdrantClient:
    api_key = settings.qdrant_api_key.get_secret_value() if settings.qdrant_api_key else None
    return AsyncQdrantClient(
        url=settings.qdrant_url,
        api_key=api_key,
        timeout=ceil(settings.provider_timeout_seconds),
        check_compatibility=False,
    )
