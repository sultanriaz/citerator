from __future__ import annotations

from pathlib import Path

import pytest

from citerator.config import get_settings
from citerator.runtime_config import overrides as ov


@pytest.fixture(autouse=True)
def _isolated(tmp_path: Path, monkeypatch):
    monkeypatch.setenv(
        "RUNTIME_CONFIG_DB_PATH", str(tmp_path / "runtime_config.sqlite")
    )
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_set_and_get_roundtrip():
    ov.set_overrides({"top_k_retrieve": 30})
    assert ov.get_overrides()["top_k_retrieve"] == 30

    ov.set_overrides({"top_k_retrieve": 40, "top_k_rerank": 8})
    assert ov.get_overrides()["top_k_retrieve"] == 40
    assert ov.get_overrides()["top_k_rerank"] == 8


def test_reject_confidence_floor_ge_threshold():
    with pytest.raises(ValueError):
        ov.set_overrides({"confidence_floor": 0.5, "confidence_threshold": 0.4})


def test_reject_rerank_gt_retrieve():
    with pytest.raises(ValueError):
        ov.set_overrides({"top_k_retrieve": 5, "top_k_rerank": 10})


def test_reject_unknown_chunking_strategy():
    with pytest.raises(ValueError):
        ov.set_overrides({"active_chunking_strategy": "magic"})


def test_reject_unknown_llm_provider():
    with pytest.raises(ValueError):
        ov.set_overrides({"llm_provider": "mistral"})


def test_reject_embedding_model_with_reingest_message():
    with pytest.raises(ValueError) as exc:
        ov.set_overrides({"embedding_model": "BAAI/bge-large-en-v1.5"})
    assert "re-ingestion" in str(exc.value).lower()


def test_reject_unknown_field():
    with pytest.raises(ValueError):
        ov.set_overrides({"qdrant_url": "http://evil:6333"})


def test_reset_specific_and_all():
    ov.set_overrides({"top_k_retrieve": 30, "rerank_model": "custom"})
    ov.reset_overrides(["top_k_retrieve"])
    remaining = ov.get_overrides()
    assert "top_k_retrieve" not in remaining
    assert remaining.get("rerank_model") == "custom"

    ov.reset_overrides()
    assert ov.get_overrides() == {}
