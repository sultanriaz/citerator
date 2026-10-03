"""Typed data models shared by every ingestion stage."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class Block(BaseModel):
    """A contiguous unit of document text (heading or paragraph)."""

    text: str
    kind: Literal["heading", "paragraph"] = "paragraph"
    level: int | None = None  # heading level, 1 = top
    page: int | None = None  # 1-based page where the block starts
    page_end: int | None = None  # page where it ends (differs after cross-page merges)

    @property
    def last_page(self) -> int | None:
        return self.page_end if self.page_end is not None else self.page


class Document(BaseModel):
    doc_id: str  # stable identity (derived from the relative path)
    doc_hash: str  # sha256 of file bytes: changes when content changes
    source_file: str  # path relative to the input folder, with forward slashes
    title: str
    doc_type: str = "unknown"  # standard | guidance | regulator_rule | internal_policy | ...
    jurisdiction: str | None = None
    effective_date: str | None = None
    page_count: int | None = None
    blocks: list[Block] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class Chunk(BaseModel):
    chunk_id: str  # deterministic UUIDv5
    doc_id: str
    doc_hash: str
    source_file: str
    doc_title: str
    doc_type: str
    jurisdiction: str | None = None
    effective_date: str | None = None
    section_path: list[str] = Field(default_factory=list)
    page_start: int | None = None
    page_end: int | None = None
    char_start: int
    char_end: int
    text: str  # original text, used for display and citations
    embed_text: str  # text that is actually embedded (section breadcrumb + text)
    token_count: int  # tokens in `text`
    embed_token_count: int  # tokens in `embed_text` (what the model actually sees)
    chunk_index: int
    chunker: str
    chunker_params: dict = Field(default_factory=dict)
