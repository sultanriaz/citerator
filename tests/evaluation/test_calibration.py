from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from citerator.evaluation import calibration
from citerator.evaluation.calibration import (
    CalibrationCoefficients,
    apply_calibration,
    fit_calibration,
    load_coefficients,
    save_coefficients,
)


def test_apply_calibration_is_monotonic():
    coeffs = CalibrationCoefficients(
        a=1.5, b=0.0, n_samples=10, n_positive=5,
        fitted_at="2026-01-01", log_loss=0.5, brier_score=0.2,
    )
    lows = [apply_calibration(s, coeffs) for s in [-4, -2, 0]]
    highs = [apply_calibration(s, coeffs) for s in [2, 4, 6]]
    assert lows == sorted(lows)
    assert highs == sorted(highs)
    assert lows[-1] < highs[0]
    assert all(0.0 <= v <= 1.0 for v in lows + highs)


def test_apply_calibration_default_coefficients():
    coeffs = CalibrationCoefficients(
        a=1.0, b=0.0, n_samples=0, n_positive=0,
        fitted_at="", log_loss=0.0, brier_score=0.0,
    )
    assert apply_calibration(0.0, coeffs) == pytest.approx(0.5, abs=1e-6)


def test_fit_calibration_requires_min_samples():
    with pytest.raises(ValueError, match="not enough samples"):
        fit_calibration([1.0, 2.0], [1, 0], min_samples=20)


def test_fit_calibration_requires_both_classes():
    with pytest.raises(ValueError, match="both positive and negative"):
        fit_calibration([1.0, 2.0, 3.0], [1, 1, 1], min_samples=3)


def test_fit_calibration_recovers_known_slope():
    """Synthetic data with a strong positive slope should fit a > 1."""

    import numpy as np

    rng = np.random.default_rng(0)
    # 200 samples, score ~ N(0, 1.5), P(positive) = sigmoid(2 * score)
    scores = rng.normal(0, 1.5, size=200).tolist()
    true_p = 1.0 / (1.0 + np.exp(-2.0 * np.asarray(scores)))
    labels = (rng.uniform(size=200) < true_p).astype(int).tolist()

    coeffs = fit_calibration(scores, labels, min_samples=20)
    assert coeffs.a > 1.0
    assert coeffs.n_samples == 200
    assert 0 <= coeffs.brier_score <= 1


def test_save_and_load_roundtrip(tmp_path: Path):
    path = tmp_path / "cal.json"
    coeffs = CalibrationCoefficients(
        a=1.234, b=-0.567, n_samples=42, n_positive=21,
        fitted_at="2026-01-01T00:00:00Z", log_loss=0.3, brier_score=0.15,
    )
    save_coefficients(coeffs, path)
    loaded = load_coefficients(path)
    assert loaded is not None
    assert loaded.a == pytest.approx(1.234)
    assert loaded.b == pytest.approx(-0.567)
    assert loaded.n_samples == 42


def test_load_coefficients_missing_file_returns_none(tmp_path: Path):
    assert load_coefficients(tmp_path / "nope.json") is None


def test_load_coefficients_corrupt_file_returns_none(tmp_path: Path):
    path = tmp_path / "bad.json"
    path.write_text("{ this is not json }", encoding="utf-8")
    assert load_coefficients(path) is None


def test_load_labels_for_fit_reads_latest_completed_run(tmp_path: Path):
    db = tmp_path / "eval.sqlite"
    conn = sqlite3.connect(str(db))
    conn.executescript(
        """
        CREATE TABLE runs (
            run_id TEXT PRIMARY KEY, created_at TEXT, status TEXT
        );
        CREATE TABLE question_results (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id TEXT, question TEXT, expected_behavior TEXT,
            faithfulness REAL
        );
        """
    )
    conn.execute(
        "INSERT INTO runs VALUES ('r1', '2026-01-01T00:00:00Z', 'completed')"
    )
    conn.execute(
        "INSERT INTO runs VALUES ('r2', '2026-02-01T00:00:00Z', 'completed')"
    )
    conn.execute(
        """
        INSERT INTO question_results
        (run_id, question, expected_behavior, faithfulness)
        VALUES ('r2', 'q1', 'answer', 0.9)
        """
    )
    conn.execute(
        """
        INSERT INTO question_results
        (run_id, question, expected_behavior, faithfulness)
        VALUES ('r2', 'q2', 'answer', 0.4)
        """
    )
    conn.execute(
        """
        INSERT INTO question_results
        (run_id, question, expected_behavior, faithfulness)
        VALUES ('r2', 'q3', 'refuse', 0.9)
        """
    )
    conn.execute(
        """
        INSERT INTO question_results
        (run_id, question, expected_behavior, faithfulness)
        VALUES ('r1', 'q_old', 'answer', 0.1)
        """
    )
    conn.commit()
    conn.close()

    labels = calibration.load_labels_for_fit(db)
    assert ("q1", 1) in labels
    assert ("q2", 0) in labels
    assert all(q != "q3" for q, _ in labels)      # refuse excluded
    assert all(q != "q_old" for q, _ in labels)   # older run excluded


def test_latest_completed_run_none_when_no_runs(tmp_path: Path):
    db = tmp_path / "empty.sqlite"
    conn = sqlite3.connect(str(db))
    conn.executescript(
        """
        CREATE TABLE runs (
            run_id TEXT PRIMARY KEY, created_at TEXT, status TEXT
        );
        CREATE TABLE question_results (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id TEXT, question TEXT, expected_behavior TEXT,
            faithfulness REAL
        );
        """
    )
    conn.commit()
    conn.close()
    assert calibration.load_labels_for_fit(db) == []