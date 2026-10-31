from functools import lru_cache
from typing import Literal

from pydantic import AnyHttpUrl, Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", case_sensitive=False, extra="ignore"
    )

    app_name: str = "Semyzbay"
    app_env: Literal["development", "test", "staging", "production"] = "development"
    debug: bool = False
    log_level: str = "INFO"
    api_v1_prefix: str = "/api/v1"
    public_base_url: AnyHttpUrl = AnyHttpUrl("http://localhost:8000")
    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:3000"])

    database_url: str = "postgresql+asyncpg://semyzbay:change_me@localhost:5432/semyzbay_db"
    database_pool_size: int = Field(default=10, ge=1)
    database_max_overflow: int = Field(default=20, ge=0)
    redis_url: str = "redis://localhost:6379/0"
    qdrant_url: str = "http://localhost:6333"
    qdrant_api_key: SecretStr | None = None
    qdrant_collection: str = "semyzbay_documents_v2"
    embedding_provider: Literal["fastembed", "openai"] = "openai"
    embedding_model: str = "text-embedding-3-large"
    embedding_dimension: int = Field(default=1024, ge=1)
    embedding_batch_size: int = Field(default=64, ge=1, le=2048)
    sparse_embedding_model: str = "Qdrant/bm25"
    document_chunk_size: int = Field(default=1200, ge=200)
    document_chunk_overlap: int = Field(default=200, ge=0)
    llm_provider: Literal["openai"] = "openai"
    llm_model: str = "gpt-6-luna"
    llm_fallback_model: str = "gpt-6.1-sol"
    llm_max_output_tokens: int = Field(default=1200, ge=64, le=16000)
    openai_api_key: SecretStr | None = None
    openai_base_url: AnyHttpUrl = AnyHttpUrl("https://api.openai.com/v1")
    openai_reasoning_effort: Literal["none", "low", "medium", "high", "xhigh", "max"] = "low"
    openai_store_responses: bool = False
    reranker_provider: Literal["lexical", "fastembed"] = "lexical"
    reranker_model: str = "BAAI/bge-reranker-v2-m3-int8"
    rag_retrieval_limit: int = Field(default=30, ge=1, le=50)
    rag_rerank_limit: int = Field(default=8, ge=1, le=20)
    rag_min_relevance_score: float = Field(default=0.05, ge=0, le=1)
    rag_max_context_chars: int = Field(default=8000, ge=500, le=50000)
    rag_max_context_chunks: int = Field(default=8, ge=1, le=20)
    rag_seed_limit: int = Field(default=4, ge=1, le=20)
    rag_neighbor_window: int = Field(default=1, ge=0, le=3)
    rag_allow_suspicious_context: bool = False

    minio_endpoint: str = "localhost:9000"
    minio_access_key: SecretStr = SecretStr("change_me")
    minio_secret_key: SecretStr = SecretStr("change_me")
    minio_secure: bool = False
    minio_documents_bucket: str = "semyzbay-documents"
    minio_audio_bucket: str = "semyzbay-audio"
    minio_generated_bucket: str = "semyzbay-generated"

    jwt_secret_key: SecretStr = SecretStr("replace_with_at_least_32_random_characters")
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = Field(default=30, ge=1)
    refresh_token_expire_days: int = Field(default=30, ge=1)

    max_upload_size_bytes: int = Field(default=50 * 1024 * 1024, ge=1)
    max_audio_duration_seconds: int = Field(default=300, ge=1)
    provider_timeout_seconds: float = Field(default=30, gt=0)
    storage_retention_days: int = Field(default=365, ge=1)
    healthcheck_timeout_seconds: float = Field(default=3, gt=0, le=30)
    default_language: Literal["kk", "ru", "en"] = "ru"

    @field_validator("api_v1_prefix")
    @classmethod
    def validate_prefix(cls, value: str) -> str:
        if not value.startswith("/") or value.endswith("/"):
            raise ValueError("API_V1_PREFIX must start with '/' and must not end with '/'")
        return value

    @field_validator("jwt_secret_key")
    @classmethod
    def validate_production_secret(cls, value: SecretStr, info: object) -> SecretStr:
        # Production validation that depends on app_env is performed by deployment checks.
        if len(value.get_secret_value()) < 32:
            raise ValueError("JWT_SECRET_KEY must contain at least 32 characters")
        return value

    @model_validator(mode="after")
    def validate_chunking(self) -> "Settings":
        if self.document_chunk_overlap >= self.document_chunk_size:
            raise ValueError("DOCUMENT_CHUNK_OVERLAP must be smaller than DOCUMENT_CHUNK_SIZE")
        if self.rag_rerank_limit > self.rag_retrieval_limit:
            raise ValueError("RAG_RERANK_LIMIT cannot exceed RAG_RETRIEVAL_LIMIT")
        if self.rag_max_context_chunks > self.rag_rerank_limit:
            raise ValueError("RAG_MAX_CONTEXT_CHUNKS cannot exceed RAG_RERANK_LIMIT")
        if self.rag_seed_limit > self.rag_rerank_limit:
            raise ValueError("RAG_SEED_LIMIT cannot exceed RAG_RERANK_LIMIT")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
