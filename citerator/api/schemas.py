"""Pydantic request/response schemas for the Citerator API."""

from __future__ import annotations

from pydantic import BaseModel

class QueryRequest(BaseModel):
    question: str
    document_scope: list[str] | None = None
    jurisdiction: str | None = None
    show_retrieval_details: bool = False


class HealthResponse(BaseModel):
    status: str
    collections: dict[str, int]