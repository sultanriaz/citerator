"""Loading and validating the labelled question set.

The JSON file is a bare array of question objects (kept compatible with
``eval/compare_chunking.py``'s existing expectations). A top-level object with
a ``questions`` key is also accepted, in case the file grows additional
metadata later.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

Category = Literal["lookup", "multi_document", "out_of_corpus", "underspecified"]
ExpectedBehavior = Literal["answer", "refuse", "clarify_or_escalate"]


class EvalQuestion(BaseModel):
    question: str
    category: Category
    expected_behavior: ExpectedBehavior
    ground_truth: str | None = None
    source_doc: str | None = None
    source_page: int | list[int] | None = None
    gold_section: str | None = None


def load_questions(path: Path) -> list[EvalQuestion]:
    """Load and validate the question set.

    Raises ``FileNotFoundError`` if the file is missing, and pydantic
    ``ValidationError`` if any question doesn't match the schema.
    """

    raw = path.read_text(encoding="utf-8")
    parsed: Any = json.loads(raw)

    if isinstance(parsed, dict):
        items = parsed.get("questions") or []
    elif isinstance(parsed, list):
        items = parsed
    else:
        raise ValueError(f"Unexpected questions file shape: {type(parsed).__name__}")

    return [EvalQuestion.model_validate(item) for item in items]
