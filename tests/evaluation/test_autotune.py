from __future__ import annotations

import json
from pathlib import Path

import pytest

from citerator.evaluation import autotune as at
from citerator.evaluation.autotune import (
    AutotuneConfig,
    ThresholdResult,
    _classify,
    _score_at_threshold,
)


def test_classify_buckets():
    assert _classify("confident", "out_of_corpus", "refuse") == "out_of_corpus"
    assert _classify("confident", "underspecified", "clarify_or_escalate") == "underspecified"
    assert _classify("confident", "lookup", "answer") == "answer"
    assert _classify("confident", "multi_document", "answer") == "answer"


def _row(raw_score: float, bucket: str) -> dict:
    return {"raw_score": raw_score, "bucket": bucket, "question": "q", "category": bucket}


def test_score_at_threshold_perfect_separation(monkeypatch):
    """When refusal questions score low and answer questions score high,
    the sweep should reflect that cleanly."""

    monkeypatch.setattr(
        "citerator.evaluation.calibration.load_coefficients",
        lambda *a, **k: None,
    )
    from citerator.retrieval import confidence as conf
    conf.reset_calibration_cache()

    rows = [
        _row(-4.0, "out_of_corpus"),
        _row(-3.0, "out_of_corpus"),
        _row(4.0, "answer"),
        _row(5.0, "answer"),
        _row(3.0, "underspecified"),
    ]

    result = _score_at_threshold(rows, threshold=0.5, floor=0.15)
    # sigmoid(-4) ~ 0.018 -> insufficient -> refuse OK
    # sigmoid( 4) ~ 0.982 -> confident -> answer OK
    # sigmoid( 3) ~ 0.953 -> confident -> escalate FAILS
    assert result.safety_refuse_pct == 1.0
    assert result.safety_escalate_pct == 0.0  # the underspecified row scored confident
    assert result.answer_rate == 1.0
    assert result.counts == {"out_of_corpus": 2, "answer": 2, "underspecified": 1}


def test_score_at_threshold_high_threshold_escalates_everything(monkeypatch):
    monkeypatch.setattr(
        "citerator.evaluation.calibration.load_coefficients",
        lambda *a, **k: None,
    )
    from citerator.retrieval import confidence as conf
    conf.reset_calibration_cache()

    rows = [
        _row(-4.0, "out_of_corpus"),  # sigmoid(-4) ~ 0.018 < floor 0.15
        _row(4.0, "answer"),
        _row(3.0, "underspecified"),
    ]
    # threshold 0.99 -> nothing reaches confident
    result = _score_at_threshold(rows, threshold=0.99, floor=0.15)
    assert result.safety_refuse_pct == 1.0
    assert result.safety_escalate_pct == 1.0
    assert result.answer_rate == 0.0


def test_score_at_threshold_empty_buckets_are_ok(monkeypatch):
    monkeypatch.setattr(
        "citerator.evaluation.calibration.load_coefficients",
        lambda *a, **k: None,
    )
    from citerator.retrieval import confidence as conf
    conf.reset_calibration_cache()

    # Only answer questions -- no out_of_corpus, no underspecified
    rows = [_row(4.0, "answer"), _row(-1.0, "answer")]
    result = _score_at_threshold(rows, threshold=0.5, floor=0.15)
    assert result.safety_refuse_pct == 1.0  # vacuous
    assert result.safety_escalate_pct == 1.0
    assert result.answer_rate == 0.5
    assert result.counts["out_of_corpus"] == 0
    assert result.counts["underspecified"] == 0


def test_autotune_picks_best_under_floors(monkeypatch):
    """End-to-end sweep with synthetic scores, no network."""

    rows = [
        _row(-4.0, "out_of_corpus"),
        _row(-3.5, "out_of_corpus"),
        _row(3.5, "answer"),
        _row(4.0, "answer"),
        _row(3.0, "answer"),
        _row(2.5, "underspecified"),
        _row(-2.0, "underspecified"),
    ]
    monkeypatch.setattr(
        "citerator.evaluation.calibration.load_coefficients",
        lambda *a, **k: None,
    )
    from citerator.retrieval import confidence as conf
    conf.reset_calibration_cache()
    monkeypatch.setattr(at, "_collect_raw_scores", lambda settings: rows)

    result = at.autotune(
        settings=None,  # type: ignore[arg-type]
        config=AutotuneConfig(min_threshold=0.30, max_threshold=0.95, step=0.05),
    )

    # Best should have high refuse, decent escalate, decent answer rate
    assert result.best.threshold >= 0.30
    assert result.best.threshold <= 0.95
    assert result.best.safety_refuse_pct >= 0.99
    assert result.best.safety_escalate_pct >= 0.99
    assert len(result.sweep) >= 10


def test_autotune_floors_unreachable_records_note(monkeypatch):
    """When no threshold satisfies the safety floors, the result is the best
    raw score and a note is added."""

    rows = [
        _row(5.0, "out_of_corpus"),   # refuser that scored high -> never refuses
        _row(-5.0, "answer"),          # answer that never gets confident
    ]
    monkeypatch.setattr(
        "citerator.evaluation.calibration.load_coefficients",
        lambda *a, **k: None,
    )
    from citerator.retrieval import confidence as conf
    conf.reset_calibration_cache()
    monkeypatch.setattr(at, "_collect_raw_scores", lambda settings: rows)

    result = at.autotune(
        settings=None,  # type: ignore[arg-type]
        config=AutotuneConfig(min_threshold=0.30, max_threshold=0.95, step=0.05),
    )
    assert any("No threshold satisfied" in n for n in result.notes)


def test_apply_persists_through_overrides(monkeypatch):
    rows = [
        _row(-4.0, "out_of_corpus"),
        _row(4.0, "answer"),
    ]
    monkeypatch.setattr(
        "citerator.evaluation.calibration.load_coefficients",
        lambda *a, **k: None,
    )
    from citerator.retrieval import confidence as conf
    conf.reset_calibration_cache()
    monkeypatch.setattr(at, "_collect_raw_scores", lambda settings: rows)

    captured: dict = {}

    def fake_set(updates, *, actor=None):
        captured.update(updates)

    from citerator.runtime_config import overrides as ov
    monkeypatch.setattr(ov, "set_overrides", fake_set)

    at.autotune(
        settings=None,  # type: ignore[arg-type]
        config=AutotuneConfig(min_threshold=0.30, max_threshold=0.95, step=0.05),
        apply=True,
    )
    assert "confidence_threshold" in captured
    assert 0.30 <= captured["confidence_threshold"] <= 0.95


def test_save_report_writes_json(tmp_path: Path):
    result = at.AutotuneResult(
        best=ThresholdResult(
            threshold=0.42,
            safety_refuse_pct=1.0,
            safety_escalate_pct=0.9,
            answer_rate=0.8,
            score=0.9,
            counts={"out_of_corpus": 5, "underspecified": 6, "answer": 11},
        ),
        sweep=[],
        evaluated_at="2026-01-01T00:00:00Z",
        question_count=22,
        config={},
        notes=[],
    )
    path = tmp_path / "at.json"
    out = at.save_report(result, path)
    assert out == path
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["best"]["threshold"] == 0.42
    assert payload["question_count"] == 22


def test_autotune_requires_questions(monkeypatch):
    monkeypatch.setattr(at, "_collect_raw_scores", lambda settings: [])
    with pytest.raises(ValueError, match="no questions scored"):
        at.autotune(settings=None)  # type: ignore[arg-type]