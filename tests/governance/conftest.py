from __future__ import annotations

from pathlib import Path

import pytest

from citerator.config import get_settings


@pytest.fixture(autouse=True)
def _isolated_governance_db(tmp_path: Path, monkeypatch):
    """Point governance at a per-test SQLite file so tests never touch
    the real governance.sqlite or the dev audit key."""

    monkeypatch.setenv("GOVERNANCE_DB_PATH", str(tmp_path / "gov.sqlite"))
    monkeypatch.setenv("AUDIT_HMAC_KEY", "test-hmac-key-at-least-32-bytes-long!")
    monkeypatch.setenv("AUDIT_REQUIRED", "false")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()