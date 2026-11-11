import httpx
import pytest

from app.core.config import Settings
from app.integrations.openai_embeddings import EmbeddingProviderError, OpenAIEmbeddingsClient


def test_embedding_vectors_are_ordered_by_index() -> None:
    client = OpenAIEmbeddingsClient(Settings(embedding_dimension=2))
    payload = {
        "data": [
            {"index": 1, "embedding": [0.3, 0.4]},
            {"index": 0, "embedding": [0.1, 0.2]},
        ]
    }
    assert client._vectors(payload, 2) == [[0.1, 0.2], [0.3, 0.4]]


def test_embedding_dimension_is_validated() -> None:
    client = OpenAIEmbeddingsClient(Settings(embedding_dimension=2))
    with pytest.raises(EmbeddingProviderError):
        client._vectors({"data": [{"index": 0, "embedding": [0.1]}]}, 1)


def _mock_client(monkeypatch: pytest.MonkeyPatch, responses: list[httpx.Response]) -> list[int]:
    calls: list[int] = []
    real_client = httpx.AsyncClient

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        return responses[min(len(calls) - 1, len(responses) - 1)]

    monkeypatch.setattr(
        "app.integrations.openai_embeddings.httpx.AsyncClient",
        lambda **kw: real_client(transport=httpx.MockTransport(handler), **kw),
    )

    async def no_sleep(_seconds: float) -> None:
        return None

    monkeypatch.setattr("app.integrations.openai_embeddings.asyncio.sleep", no_sleep)
    return calls


def _settings() -> Settings:
    return Settings(_env_file=None, embedding_dimension=2, openai_api_key="sk-test")


async def test_rate_limit_is_retried(monkeypatch: pytest.MonkeyPatch) -> None:
    rate_limited = httpx.Response(
        429, json={"error": {"code": "rate_limit_exceeded"}}, headers={"retry-after": "1"}
    )
    ok = httpx.Response(200, json={"data": [{"index": 0, "embedding": [0.1, 0.2]}]})
    calls = _mock_client(monkeypatch, [rate_limited, ok])

    assert await OpenAIEmbeddingsClient(_settings()).embed(["тест"]) == [[0.1, 0.2]]
    assert len(calls) == 2


async def test_exhausted_quota_fails_fast_with_code(monkeypatch: pytest.MonkeyPatch) -> None:
    quota = httpx.Response(
        429, json={"error": {"code": "insufficient_quota", "type": "insufficient_quota"}}
    )
    calls = _mock_client(monkeypatch, [quota])

    with pytest.raises(EmbeddingProviderError, match="HTTP 429 code=insufficient_quota"):
        await OpenAIEmbeddingsClient(_settings()).embed(["тест"])
    assert len(calls) == 1


async def test_exhausted_credits_fail_fast(monkeypatch: pytest.MonkeyPatch) -> None:
    # Real OpenAI response when the prepaid balance is empty.
    credits = httpx.Response(
        429,
        json={"error": {"type": "insufficient_quota", "code": "credit_balance_exhausted"}},
    )
    calls = _mock_client(monkeypatch, [credits])

    with pytest.raises(EmbeddingProviderError, match="code=credit_balance_exhausted"):
        await OpenAIEmbeddingsClient(_settings()).embed(["тест"])
    assert len(calls) == 1


async def test_persistent_rate_limit_gives_up_after_three_attempts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = _mock_client(
        monkeypatch, [httpx.Response(429, json={"error": {"code": "rate_limit_exceeded"}})]
    )
    with pytest.raises(EmbeddingProviderError, match="code=rate_limit_exceeded"):
        await OpenAIEmbeddingsClient(_settings()).embed(["тест"])
    assert len(calls) == 3
