"""Merge base Settings with persisted runtime overrides.

This is the function registered as a dependency override in
citerator/api/app.py, replacing get_settings for every FastAPI route. It
reads overrides from sqlite on every call -- no in-process caching of the
merged result -- so a change made through /settings/* is visible to the very
next request across the whole app.

The base settings object (get_settings()) is never mutated; model_copy
returns a new instance. Other code that holds a reference to the base
continues to see the env-derived values.
"""

from __future__ import annotations

from citerator.config import Settings, get_settings
from citerator.runtime_config.overrides import get_overrides


def get_effective_settings() -> Settings:
    base = get_settings()
    overrides = get_overrides()
    if not overrides:
        return base.model_copy()
    return base.model_copy(update=overrides)
