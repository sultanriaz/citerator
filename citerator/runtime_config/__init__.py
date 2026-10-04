"""Runtime overrides for a subset of Settings fields.

The store (overrides.py) persists key-value overrides in SQLite. The merger
(effective_settings.py) reads them fresh on every call and returns a new
Settings instance, so changes made through /settings/* take effect on the
next request without a process restart and survive restarts because they
live in sqlite, not in memory.
"""
