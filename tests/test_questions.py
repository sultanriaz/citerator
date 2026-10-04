from __future__ import annotations

import json
from pathlib import Path

from citerator.evaluation.questions import EvalQuestion, load_questions


def test_real_questions_file_loads() -> None:
    path = Path("eval/questions.json")
    assert path.exists(), "eval/questions.json must exist for Phase 5"

    questions = load_questions(path)
    assert len(questions) >= 20

    categories = {q.category for q in questions}
    behaviors = {q.expected_behavior for q in questions}

    assert {"lookup", "multi_document", "out_of_corpus", "underspecified"} <= categories
    assert {"answer", "refuse", "clarify_or_escalate"} <= behaviors

    for q in questions:
        if q.expected_behavior == "answer":
            assert q.ground_truth, f"'answer' question missing ground_truth: {q.question}"


def test_load_accepts_wrapped_object(tmp_path: Path) -> None:
    payload = {
        "questions": [
            {
                "question": "Q",
                "category": "lookup",
                "expected_behavior": "answer",
                "ground_truth": "G",
            }
        ]
    }
    path = tmp_path / "q.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    loaded = load_questions(path)
    assert len(loaded) == 1
    assert isinstance(loaded[0], EvalQuestion)
    assert loaded[0].question == "Q"
