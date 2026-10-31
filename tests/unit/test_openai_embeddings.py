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
