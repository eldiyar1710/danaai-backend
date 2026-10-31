from typing import Any
from uuid import uuid4

import httpx

from app.core.config import Settings


class EmbeddingProviderError(RuntimeError):
    pass


class OpenAIEmbeddingsClient:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def _api_key(self) -> str:
        if self.settings.openai_api_key is None:
            raise EmbeddingProviderError("OPENAI_API_KEY is not configured")
        value = self.settings.openai_api_key.get_secret_value().strip()
        if not value:
            raise EmbeddingProviderError("OPENAI_API_KEY is not configured")
        return value

    async def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        vectors: list[list[float]] = []
        for offset in range(0, len(texts), self.settings.embedding_batch_size):
            batch = texts[offset : offset + self.settings.embedding_batch_size]
            vectors.extend(await self._embed_batch(batch))
        return vectors

    async def _embed_batch(self, texts: list[str]) -> list[list[float]]:
        url = f"{str(self.settings.openai_base_url).rstrip('/')}/embeddings"
        body = {
            "model": self.settings.embedding_model,
            "input": texts,
            "dimensions": self.settings.embedding_dimension,
            "encoding_format": "float",
        }
        try:
            async with httpx.AsyncClient(timeout=self.settings.provider_timeout_seconds) as client:
                response = await client.post(
                    url,
                    headers={
                        "Authorization": f"Bearer {self._api_key()}",
                        "Content-Type": "application/json",
                        "X-Client-Request-Id": str(uuid4()),
                    },
                    json=body,
                )
        except httpx.HTTPError as exc:
            raise EmbeddingProviderError("OpenAI embeddings request failed") from exc
        if response.status_code >= 400:
            request_id = response.headers.get("x-request-id", "unknown")
            raise EmbeddingProviderError(
                f"OpenAI embeddings returned HTTP {response.status_code} "
                f"(request_id={request_id})"
            )
        return self._vectors(response.json(), len(texts))

    def _vectors(self, payload: dict[str, Any], expected_count: int) -> list[list[float]]:
        data = payload.get("data")
        if not isinstance(data, list) or len(data) != expected_count:
            raise EmbeddingProviderError("OpenAI returned an unexpected embedding count")
        ordered = sorted(data, key=lambda item: int(item.get("index", -1)))
        vectors: list[list[float]] = []
        for expected_index, item in enumerate(ordered):
            if int(item.get("index", -1)) != expected_index:
                raise EmbeddingProviderError("OpenAI returned invalid embedding indices")
            vector = item.get("embedding")
            if not isinstance(vector, list) or len(vector) != self.settings.embedding_dimension:
                raise EmbeddingProviderError("OpenAI returned an invalid embedding dimension")
            vectors.append([float(value) for value in vector])
        return vectors
