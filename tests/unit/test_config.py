import pytest
from pydantic import ValidationError

from app.core.config import Settings


def test_api_prefix_is_normalized_contract() -> None:
    settings = Settings(api_v1_prefix="/api/v1")
    assert settings.api_v1_prefix == "/api/v1"


@pytest.mark.parametrize("value", ["api/v1", "/api/v1/"])
def test_invalid_api_prefix_is_rejected(value: str) -> None:
    with pytest.raises(ValidationError):
        Settings(api_v1_prefix=value)


def test_short_jwt_secret_is_rejected() -> None:
    with pytest.raises(ValidationError):
        Settings(jwt_secret_key="short")


def test_invalid_rag_limits_are_rejected() -> None:
    with pytest.raises(ValidationError):
        Settings(rag_retrieval_limit=5, rag_rerank_limit=6)


def test_default_llm_configuration_is_cost_controlled() -> None:
    settings = Settings()
    assert settings.llm_model == "gpt-6-luna"
    assert settings.llm_fallback_model == "gpt-6.1-sol"
    assert settings.openai_reasoning_effort == "low"
    assert settings.openai_store_responses is False


def test_default_embedding_configuration_uses_openai() -> None:
    settings = Settings()
    assert settings.embedding_provider == "openai"
    assert settings.embedding_model == "text-embedding-3-large"
    assert settings.embedding_dimension == 1024
    assert settings.qdrant_collection == "semyzbay_documents_v2"
