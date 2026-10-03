"""Central settings loaded from environment variables (.env)."""
from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # LLM
    llm_provider: str = "openai"
    openai_api_key: str = ""
    anthropic_api_key: str = ""
    llm_model: str = ""

    # Vector store. Accepts an http(s) URL, ":memory:", or a folder path for local mode.
    qdrant_url: str = "http://localhost:6333"
    qdrant_collection: str = "citerator_chunks"

    # Models
    embedding_model: str = "BAAI/bge-base-en-v1.5"
    rerank_model: str = "cross-encoder/ms-marco-MiniLM-L-6-v2"

    # Retrieval / guardrail
    top_k_retrieve: int = 20
    top_k_rerank: int = 5
    confidence_threshold: float = 0.30

    # API
    api_key: str = "change-me"


@lru_cache
def get_settings() -> Settings:
    return Settings()
