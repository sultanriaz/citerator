from __future__ import annotations

from citerator.evaluation.ragas_scorer import FakeRagasScorer, RagasScores


def test_fake_scorer_returns_all_four_when_ground_truth_present() -> None:
    scorer = FakeRagasScorer()
    scores = scorer.score(
        question="What is the threshold?",
        answer="The threshold is USD 15,000",
        contexts=["The threshold is USD 15,000 for one-off transactions."],
        ground_truth="USD 15,000",
    )
    assert isinstance(scores, RagasScores)
    assert scores.faithfulness is not None
    assert scores.answer_relevancy is not None
    assert scores.context_precision is not None
    assert scores.context_recall is not None


def test_fake_scorer_returns_none_for_context_metrics_without_ground_truth() -> None:
    scorer = FakeRagasScorer()
    scores = scorer.score(
        question="What is the threshold?",
        answer="The threshold is USD 15,000",
        contexts=["The threshold is USD 15,000 for one-off transactions."],
        ground_truth=None,
    )
    assert scores.faithfulness is not None
    assert scores.answer_relevancy is not None
    assert scores.context_precision is None
    assert scores.context_recall is None


def test_fake_scorer_is_deterministic() -> None:
    scorer = FakeRagasScorer()
    args = dict(
        question="Q", answer="A B C", contexts=["A B"], ground_truth="A B"
    )
    assert scorer.score(**args) == scorer.score(**args)
