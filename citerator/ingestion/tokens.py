"""Tokenizers that expose character offsets, so chunk sizes are measured in tokens.

Chunk size must be measured with the same tokenizer as the embedding model: BGE has a
512-token limit and silently truncates anything longer.
"""
from __future__ import annotations

import logging
import re
from typing import Protocol

log = logging.getLogger("citerator.tokens")

_TOKEN_RE = re.compile(r"\w+|[^\w\s]", re.UNICODE)


class Tokenizer(Protocol):
    name: str
    exact: bool  # True when counts match the embedding model's real tokenizer

    def offsets(self, text: str) -> list[tuple[int, int]]: ...

    def count(self, text: str) -> int: ...


class RegexTokenizer:
    """Approximation: one token per word or punctuation mark.

    Real wordpiece/BPE tokenizers usually produce MORE tokens than this (roughly 1.2-1.4x
    for English), so keep a safety margin below the model limit when this is in use.
    """

    name = "regex-approx"
    exact = False

    def offsets(self, text: str) -> list[tuple[int, int]]:
        return [m.span() for m in _TOKEN_RE.finditer(text)]

    def count(self, text: str) -> int:
        return sum(1 for _ in _TOKEN_RE.finditer(text))


class HFTokenizer:
    """Hugging Face fast tokenizer (same vocabulary as the embedding model)."""

    exact = True

    def __init__(self, model_name: str):
        from transformers import AutoTokenizer

        self.name = model_name
        self._tok = AutoTokenizer.from_pretrained(model_name, use_fast=True)
        self._tok.model_max_length = 10**9  # we deliberately tokenize whole documents

    def offsets(self, text: str) -> list[tuple[int, int]]:
        if not text:
            return []
        enc = self._tok(text, add_special_tokens=False, return_offsets_mapping=True, truncation=False)
        return [tuple(o) for o in enc["offset_mapping"]]

    def count(self, text: str) -> int:
        if not text:
            return 0
        return len(self._tok(text, add_special_tokens=False, truncation=False)["input_ids"])


def get_tokenizer(model_name: str | None) -> Tokenizer:
    """Return an HF tokenizer for `model_name`, or fall back to the regex approximation."""
    if not model_name:
        return RegexTokenizer()
    try:
        return HFTokenizer(model_name)
    except Exception as exc:  # offline, missing dependency, unknown model
        log.warning("Could not load tokenizer %s (%s); using approximate regex tokenizer", model_name, exc)
        return RegexTokenizer()
