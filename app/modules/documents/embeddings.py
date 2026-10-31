import asyncio
from functools import lru_cache

from fastembed import SparseTextEmbedding, TextEmbedding

from app.core.config import Settings
from app.integrations.openai_embeddings import OpenAIEmbeddingsClient


@lru_cache(maxsize=4)
def dense_model(model_name: str, cache_dir: str) -> TextEmbedding:
    return TextEmbedding(model_name, cache_dir=cache_dir, lazy_load=True)


@lru_cache(maxsize=4)
def sparse_model(model_name: str, cache_dir: str) -> SparseTextEmbedding:
    return SparseTextEmbedding(model_name, cache_dir=cache_dir, lazy_load=True)


async def embed_dense(
    settings: Settings, texts: list[str], *, query: bool = False
) -> list[list[float]]:
    if settings.embedding_provider == "openai":
        return await OpenAIEmbeddingsClient(settings).embed(texts)
    model = dense_model(settings.embedding_model, settings.fastembed_cache_path)
    if query:
        raw = await asyncio.to_thread(lambda: list(model.query_embed(texts)))
    else:
        raw = await asyncio.to_thread(lambda: list(model.embed(texts)))
    return [vector.tolist() for vector in raw]
