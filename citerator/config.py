"""Application settings for Citerator.

Phase 3 retrieval/generation/API, Phase 4 documents, Phase 5 evaluation,
Phase 6 runtime settings + rate limit, Phase 7 observability + escalation.

get_settings() returns the immutable base settings from .env / class
defaults. Runtime overrides applied via the Settings screen live in
citerator/runtime_config/overrides.py and are merged on top by
citerator/runtime_config/effective_settings.py, which is registered as a
FastAPI dependency_override in citerator/api/app.py.
"""

from functools import lru_cache

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    llm_provider: str = "openai"
    openai_api_key: str = ""
    anthropic_api_key: str = ""
    gemini_api_key: str = ""
    llm_model: str = ""

    qdrant_url: str = "http://localhost:6333"
    qdrant_collection: str = "citerator_chunks"
    embedding_model: str = "BAAI/bge-base-en-v1.5"
    rerank_model: str = "cross-encoder/ms-marco-MiniLM-L-6-v2"
    top_k_retrieve: int = 20
    top_k_rerank: int = 5
    confidence_threshold: float = 0.30
    api_key: str = "change-me"

    embedder_kind: str = "bge"
    sparse_kind: str = "bm25"
    active_chunking_strategy: str = "structure"
    confidence_floor: float = 0.15
    cors_origins: list[str] = ["http://localhost:3000"]

    documents_root: str = "data/raw"
    documents_db_path: str = "data/processed/documents.sqlite"
    max_upload_mb: int = 50
    max_concurrent_ingest_jobs: int = 2

    eval_db_path: str = "data/processed/eval.sqlite"
    eval_questions_path: str = "eval/questions.json"
    ragas_llm_provider: str = ""
    ragas_llm_model: str = ""
    max_concurrent_eval_runs: int = 1
    llm_price_per_million_input_tokens: float | None = None
    llm_price_per_million_output_tokens: float | None = None

    rate_limit_requests_per_minute: int = 120

    governance_db_path: str = "data/processed/governance.sqlite"
    audit_hmac_key: str = ""
    audit_required: bool = True
    audit_max_response_bytes: int = 1_000_000
    document_default_classification: str = "internal"
    document_default_retention_days: int | None = None
    document_review_cycle_days: int = 365
    erasure_max_chunks_per_run: int = 10_000

    stream_enabled: bool = True
    stream_heartbeat_seconds: int = 15

    cache_enabled: bool = False
    cache_backend: str = "memory"
    cache_redis_url: str = "redis://localhost:6379/0"
    cache_ttl_seconds: int = 3600
    cache_max_entries: int = 1000
    cache_similarity_threshold: float = 0.95
    cache_embedding_model: str = ""

    queue_backend: str = "inline"
    queue_redis_url: str = "redis://localhost:6379/1"
    queue_name: str = "citerator"
    queue_job_timeout_seconds: int = 900
    queue_result_ttl_seconds: int = 86400
    runtime_config_db_path: str = "data/processed/runtime_config.sqlite"

    langfuse_public_key: str = ""
    langfuse_secret_key: str = ""
    langfuse_host: str = "https://cloud.langfuse.com"
    enable_tracing: bool = True
    escalation_webhook_url: str | None = None
    observability_db_path: str = "data/processed/observability.sqlite"

    @model_validator(mode="after")
    def _validate_confidence_bands(self) -> "Settings":
        if self.confidence_floor >= self.confidence_threshold:
            raise ValueError("confidence_floor must be less than confidence_threshold")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()


def base_settings() -> Settings:
    return get_settings()
