from __future__ import annotations

from pathlib import Path

import pytest

from citerator.config import get_settings
from citerator.runtime_config import overrides as ov
from citerator.runtime_config.effective_settings import get_effective_settings


@pytest.fixture(autouse=True)
def _isolated(tmp_path: Path, monkeypatch):
    monkeypatch.setenv(
        "RUNTIME_CONFIG_DB_PATH", str(tmp_path / "runtime_config.sqlite")
    )
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_override_reflected_without_mutating_base():
    base = get_settings()
    original = base.top_k_retrieve
    original_id = id(base)

    ov.set_overrides({"top_k_retrieve": 33})

    effective = get_effective_settings()
    assert effective.top_k_retrieve == 33

    # base object untouched
    assert get_settings().top_k_retrieve == original
    assert id(get_settings()) == original_id


def test_fresh_call_sees_persisted_override():
    ov.set_overrides({"top_k_retrieve": 17})
    assert get_effective_settings().top_k_retrieve == 17

    # Simulate a "fresh" process: clear the lru_cache on get_settings.
    get_settings.cache_clear()
    assert get_effective_settings().top_k_retrieve == 17


def test_returns_new_instance_each_call():
    a = get_effective_settings()
    b = get_effective_settings()
    assert a is not b
    assert a.model_dump() == b.model_dump()


def test_effective_merges_multiple_fields():
    ov.set_overrides({"top_k_retrieve": 50, "top_k_rerank": 9})
    e = get_effective_settings()
    assert e.top_k_retrieve == 50
    assert e.top_k_rerank == 9
