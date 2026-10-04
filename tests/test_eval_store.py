from __future__ import annotations

from pathlib import Path

import pytest

from citerator.evaluation import store


@pytest.fixture
def db(tmp_path: Path) -> str:
    return str(tmp_path / "eval.sqlite")


def _make_run(db: str, label: str = "run"):
    return store.create_run(
        question_set_path="eval/questions.json",
        chunking_strategy="structure",
        embedder="hash",
        sparse_embedder="hash",
        rerank_model="fake",
        llm_provider="fake",
        llm_model="fake",
        top_k_retrieve=10,
        top_k_rerank=5,
        confidence_threshold=0.30,
        confidence_floor=0.15,
        label=label,
        db_path=db,
    )


def test_create_and_get_run(db: str) -> None:
    run_id = _make_run(db, "baseline")
    run = store.get_run(run_id, db_path=db)
    assert run is not None
    assert run["label"] == "baseline"
    assert run["status"] == "running"
    assert run["question_count"] == 0


def test_update_run_and_aggregates(db: str) -> None:
    run_id = _make_run(db)
    store.update_run(
        run_id,
        db_path=db,
        status="completed",
        faithfulness_mean=0.9,
        safety_refuse_pct=100.0,
    )
    run = store.get_run(run_id, db_path=db)
    assert run["status"] == "completed"
    assert run["faithfulness_mean"] == 0.9


def test_list_runs_newest_first(db: str) -> None:
    a = _make_run(db, "a")
    b = _make_run(db, "b")
    rows = store.list_runs(db_path=db)
    assert [r["run_id"] for r in rows] == [b, a]


def test_question_results_and_category_filter(db: str) -> None:
    run_id = _make_run(db)
    store.add_question_result(
        run_id,
        db_path=db,
        question="Q1",
        category="lookup",
        expected_behavior="answer",
        state="confident",
        passed=True,
        retrieved_chunk_ids=["c1", "c2"],
        cited_chunk_ids=["c1"],
    )
    store.add_question_result(
        run_id,
        db_path=db,
        question="Q2",
        category="out_of_corpus",
        expected_behavior="refuse",
        state="insufficient",
        passed=True,
    )

    all_rows = store.list_question_results(run_id, db_path=db)
    assert len(all_rows) == 2
    assert all_rows[0]["retrieved_chunk_ids"] == ["c1", "c2"]
    assert all_rows[0]["passed"] is True

    lookups = store.list_question_results(run_id, category="lookup", db_path=db)
    assert len(lookups) == 1
    assert lookups[0]["question"] == "Q1"
