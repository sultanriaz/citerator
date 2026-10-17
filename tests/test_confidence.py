from __future__ import annotations

import pytest

import math

from citerator.config import Settings
from citerator.retrieval.confidence import score_confidence
from citerator.retrieval.search import RetrievedChunk


def _chunk(score: float) -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id="c1",
        doc_id="doc",
        doc_hash="hash",
        source_file="source.md",
        doc_title="Title",
        doc_type="policy",
        section_path=["1"],
        char_start=0,
        char_end=1,
        text="text",
        token_count=1,
        embed_token_count=1,
        chunk_index=0,
        chunker="test",
        chunker_params={},
        rerank_score=score,
    )


def test_confidence_boundaries() -> None:
    settings = Settings(confidence_threshold=0.30, confidence_floor=0.15)

    threshold_logit = math.log(0.30 / 0.70)
    floor_logit = math.log(0.15 / 0.85)

    assert score_confidence([_chunk(threshold_logit)], settings).state == "confident"
    assert score_confidence([_chunk(floor_logit)], settings).state == "low_confidence"
    assert score_confidence([_chunk(floor_logit - 0.01)], settings).state == "insufficient"


def test_empty_retrieval_is_insufficient() -> None:
    settings = Settings()
    result = score_confidence([], settings)

    assert result.state == "insufficient"
    assert result.has_candidates is False
    assert result.confidence == 0.0

def test_calibrated_path_uses_coefficients(monkeypatch, tmp_path):
    """When coefficients exist, _normalize uses the calibrated curve."""

    import json
    from citerator.evaluation import calibration
    from citerator.retrieval import confidence as conf

    cal_path = tmp_path / "cal.json"
    cal_path.write_text(
        json.dumps(
            {
                "a": 1.0,
                "b": 0.0,
                "n_samples": 50,
                "n_positive": 25,
                "fitted_at": "2026-01-01",
                "log_loss": 0.5,
                "brier_score": 0.2,
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(calibration, "DEFAULT_PATH", cal_path)
    conf.reset_calibration_cache()

    # With a=1, b=0, calibrated(0.0) == raw sigmoid(0.0) == 0.5
    assert conf._normalize(0.0) == pytest.approx(0.5, abs=1e-6)

    # Now test with a non-trivial curve
    cal_path.write_text(
        json.dumps(
            {
                "a": 3.0,
                "b": 1.0,
                "n_samples": 50,
                "n_positive": 25,
                "fitted_at": "2026-01-01",
                "log_loss": 0.5,
                "brier_score": 0.2,
            }
        ),
        encoding="utf-8",
    )
    conf.reset_calibration_cache()

    # sigmoid(3*0 + 1) = sigmoid(1) ~ 0.731
    assert conf._normalize(0.0) > 0.70
    assert conf._normalize(0.0) < 0.75

    conf.reset_calibration_cache()


def test_no_calibration_file_falls_back_to_sigmoid(monkeypatch, tmp_path):
    from citerator.evaluation import calibration
    from citerator.retrieval import confidence as conf

    monkeypatch.setattr(calibration, "DEFAULT_PATH", tmp_path / "nope.json")
    conf.reset_calibration_cache()

    # Raw sigmoid(0) == 0.5
    assert conf._normalize(0.0) == pytest.approx(0.5, abs=1e-6)
    # Raw sigmoid(2) == 0.8808
    assert conf._normalize(2.0) == pytest.approx(0.8808, abs=1e-3)

    conf.reset_calibration_cache()