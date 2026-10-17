"""Confidence calibration via logistic regression.

The pipeline's raw confidence is sigmoid(rerank_score) -- a heuristic mapping
that ignores the actual relationship between cross-encoder scores and
correctness on this corpus. This module fits that mapping to real data.

Training target (independent of the pipeline's own confidence band):

    feature = top-1 rerank score for the question
    label   = 1 if faithfulness >= 0.7 else 0

faithfulness comes from Ragas scoring of the generated answer. It is not
derived from state or confidence, so fitting to it is not circular. A high
top rerank score that produces an unfaithful answer correctly pulls the
curve down; a low score that produces a faithful answer pulls it up.

Fit method: unregularized logistic regression (scikit-learn, already a
ragas dependency). Two parameters -- slope and intercept -- is the right
complexity for the sample sizes available. A richer model (splines, isotonic
regression) would overfit 20-100 samples.

Coefficients are stored as JSON so they survive process restarts.
retrieval/confidence.py reads them lazily with a short cache TTL, so a
refit takes effect on the next request.

Fallback: no coefficients file, unreadable file, or fewer than min_samples
usable pairs -> retrieval/confidence.py uses raw sigmoid, same as before.
The calibrator degrades to prior behavior rather than failing hard.
"""

from __future__ import annotations

import json
import math
import sqlite3
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import structlog

logger = structlog.get_logger(__name__)

DEFAULT_PATH = Path("data/processed/calibration.json")
DEFAULT_MIN_SAMPLES = 20
DEFAULT_FAITHFULNESS_THRESHOLD = 0.7


@dataclass(frozen=True)
class CalibrationCoefficients:
    a: float
    b: float
    n_samples: int
    n_positive: int
    fitted_at: str
    log_loss: float
    brier_score: float


def _sigmoid(x: float) -> float:
    if x >= 0:
        z = math.exp(-x)
        return 1.0 / (1.0 + z)
    z = math.exp(x)
    return z / (1.0 + z)


def apply_calibration(
    raw_score: float, coeffs: CalibrationCoefficients
) -> float:
    return _sigmoid(coeffs.a * raw_score + coeffs.b)


def load_coefficients(
    path: Path | None = None,
) -> CalibrationCoefficients | None:
    p = path or DEFAULT_PATH
    if not p.exists():
        return None
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        return CalibrationCoefficients(
            a=float(data["a"]),
            b=float(data["b"]),
            n_samples=int(data.get("n_samples", 0)),
            n_positive=int(data.get("n_positive", 0)),
            fitted_at=str(data.get("fitted_at", "")),
            log_loss=float(data.get("log_loss", 0.0)),
            brier_score=float(data.get("brier_score", 0.0)),
        )
    except Exception as exc:
        logger.warning("calibration_load_failed", path=str(p), error=str(exc))
        return None


def save_coefficients(
    coeffs: CalibrationCoefficients, path: Path | None = None
) -> None:
    p = path or DEFAULT_PATH
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(asdict(coeffs), indent=2), encoding="utf-8")


def fit_calibration(
    scores: list[float],
    labels: list[int],
    *,
    min_samples: int = DEFAULT_MIN_SAMPLES,
) -> CalibrationCoefficients:
    if len(scores) != len(labels):
        raise ValueError("scores and labels must be the same length")
    if len(scores) < min_samples:
        raise ValueError(
            f"not enough samples to fit: {len(scores)} < {min_samples}"
        )
    if len(set(labels)) < 2:
        raise ValueError("need both positive and negative labels to fit")

    import numpy as np
    from sklearn.linear_model import LogisticRegression

    X = np.asarray(scores, dtype=float).reshape(-1, 1)
    y = np.asarray(labels, dtype=int)

    # C=1e9 approximates unregularized regression without the deprecated
    # penalty=None kwarg (removed in scikit-learn 1.10).
    model = LogisticRegression(C=1e9, solver="lbfgs", max_iter=1000)
    model.fit(X, y)

    a = float(model.coef_[0][0])
    b = float(model.intercept_[0])
    probs = model.predict_proba(X)[:, 1]

    eps = 1e-12
    log_loss = float(
        -np.mean(y * np.log(probs + eps) + (1 - y) * np.log(1 - probs + eps))
    )
    brier = float(np.mean((probs - y) ** 2))

    return CalibrationCoefficients(
        a=a,
        b=b,
        n_samples=len(scores),
        n_positive=int(y.sum()),
        fitted_at=datetime.now(timezone.utc).isoformat(),
        log_loss=log_loss,
        brier_score=brier,
    )


def _latest_completed_run_id(db_path: Path) -> str | None:
    if not db_path.exists():
        return None
    conn = sqlite3.connect(str(db_path))
    try:
        row = conn.execute(
            """
            SELECT run_id FROM runs
            WHERE status = 'completed'
            ORDER BY created_at DESC
            LIMIT 1
            """
        ).fetchone()
    finally:
        conn.close()
    return row[0] if row else None


def load_labels_for_fit(
    db_path: Path,
    *,
    faithfulness_threshold: float = DEFAULT_FAITHFULNESS_THRESHOLD,
) -> list[tuple[str, int]]:
    """Return (question_text, label) pairs from the latest completed run."""

    run_id = _latest_completed_run_id(db_path)
    if not run_id:
        return []
    conn = sqlite3.connect(str(db_path))
    try:
        rows = conn.execute(
            """
            SELECT question, faithfulness
            FROM question_results
            WHERE run_id = ?
              AND expected_behavior = 'answer'
              AND faithfulness IS NOT NULL
            """,
            (run_id,),
        ).fetchall()
    finally:
        conn.close()
    return [(q, 1 if f >= faithfulness_threshold else 0) for q, f in rows]


def collect_scores_for_questions(
    questions: list[Any],
    settings: Any,
) -> dict[str, float]:
    """Re-run retrieval+rerank for each question, return {question_text: top_score}.

    No LLM call, no Ragas scoring -- just the reranker's top-1 score.
    Deterministic given a stable collection.
    """

    from citerator.ingestion.embedding import get_embedder, get_sparse_embedder
    from citerator.ingestion.store import make_client
    from citerator.retrieval.rerank import CrossEncoderReranker, rerank
    from citerator.retrieval.search import search

    embedder = get_embedder(
        settings.embedder_kind, settings.embedding_model or None
    )
    sparse = get_sparse_embedder(settings.sparse_kind)
    client = make_client(settings.qdrant_url)
    reranker = CrossEncoderReranker(settings.rerank_model)

    out: dict[str, float] = {}
    for q in questions:
        try:
            candidates = search(
                q.question,
                settings,
                client=client,
                embedder=embedder,
                sparse_embedder=sparse,
            )
            reranked = rerank(
                q.question, candidates, settings, reranker=reranker
            )
            if reranked and reranked[0].rerank_score is not None:
                out[q.question] = float(reranked[0].rerank_score)
        except Exception as exc:
            logger.warning(
                "calibration_score_failed", question=q.question, error=str(exc)
            )
    return out


def fit_and_save(
    settings: Any,
    *,
    db_path: Path | None = None,
    output_path: Path | None = None,
    min_samples: int = DEFAULT_MIN_SAMPLES,
    faithfulness_threshold: float = DEFAULT_FAITHFULNESS_THRESHOLD,
) -> CalibrationCoefficients:
    from citerator.evaluation.questions import load_questions

    questions = load_questions(Path(settings.eval_questions_path))
    scores = collect_scores_for_questions(questions, settings)

    db = Path(db_path) if db_path else Path(settings.eval_db_path)
    labels = load_labels_for_fit(
        db, faithfulness_threshold=faithfulness_threshold
    )

    paired: list[tuple[float, int]] = []
    for q_text, label in labels:
        if q_text in scores:
            paired.append((scores[q_text], label))

    if len(paired) < min_samples:
        raise ValueError(
            f"not enough paired samples: {len(paired)} < {min_samples}. "
            f"Run at least one eval on the current corpus before calibrating."
        )

    score_list = [s for s, _ in paired]
    label_list = [l for _, l in paired]

    coeffs = fit_calibration(
        score_list, label_list, min_samples=min_samples
    )
    save_coefficients(coeffs, output_path)
    logger.info(
        "calibration_fitted",
        n_samples=coeffs.n_samples,
        n_positive=coeffs.n_positive,
        slope=round(coeffs.a, 4),
        intercept=round(coeffs.b, 4),
        brier=round(coeffs.brier_score, 4),
    )
    return coeffs


if __name__ == "__main__":
    from citerator.config import get_settings

    settings = get_settings()
    print("Fitting calibration from eval history + current collection...")
    coeffs = fit_and_save(settings)
    print(f"  slope      a = {coeffs.a:.6f}")
    print(f"  intercept  b = {coeffs.b:.6f}")
    print(f"  samples      = {coeffs.n_samples} ({coeffs.n_positive} positive)")
    print(f"  log loss     = {coeffs.log_loss:.4f}")
    print(f"  Brier score  = {coeffs.brier_score:.4f}")
    print(f"  Saved to {DEFAULT_PATH}")