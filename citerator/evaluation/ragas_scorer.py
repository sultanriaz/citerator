"""Ragas-backed scoring with a deterministic offline Fake.

The real scorer lazy-imports ``ragas`` inside ``__init__`` -- same pattern as
embedding.py's OpenAIEmbedder. All ragas API churn (LLM wrapper, embeddings
wrapper, dataset shape, result extraction) is isolated here so the runner
never sees it.

``FakeRagasScorer`` derives scores from naive substring overlap. It is NOT a
quality signal -- it exists so tests and offline runs are deterministic.
"""

from __future__ import annotations

from typing import NamedTuple, Protocol

import structlog

from citerator.config import Settings

logger = structlog.get_logger(__name__)


class RagasScores(NamedTuple):
    faithfulness: float | None
    answer_relevancy: float | None
    context_precision: float | None
    context_recall: float | None


class RagasScorer(Protocol):
    def score(
        self,
        question: str,
        answer: str,
        contexts: list[str],
        ground_truth: str | None,
    ) -> RagasScores:
        ...


class RealRagasScorer:
    """Wraps the installed ``ragas`` package with Gemini as the judge LLM.

    Construction is deferred to the first ``score`` call. Any failure -- old
    langchain imports, missing embeddings backend, ragas API drift, or an
    extraction shape we don't recognise -- degrades to all-None scores with a
    warning rather than killing the run.
    """

    def __init__(self, settings: Settings):
        self.settings = settings
        self._llm = None
        self._embeddings = None
        self._metrics = None
        self._init_error: str | None = None
        self._debug_done = False

    def _ensure_initialized(self) -> bool:
        if self._metrics is not None:
            return True
        if self._init_error is not None:
            return False
        try:
            import ragas  # noqa: F401

            self._llm = self._build_llm()
            self._embeddings = self._build_embeddings()
            self._metrics = self._build_metrics()
            return True
        except Exception as exc:
            self._init_error = str(exc)
            logger.warning("ragas_init_failed", error=str(exc))
            return False

    def _provider(self) -> str:
        return (
            self.settings.ragas_llm_provider or self.settings.llm_provider
        ).lower()

    def _model(self) -> str:
        model = self.settings.ragas_llm_model or self.settings.llm_model
        if self._provider() in {"gemini", "google"}:
            return model or "gemini-2.5-flash"
        if self._provider() == "openai":
            return model or "gpt-4o-mini"
        if self._provider() == "anthropic":
            return model or "claude-3-haiku-20240307"
        return model

    def _build_llm(self):
        from ragas.llms import LangchainLLMWrapper

        provider = self._provider()

        if provider in {"gemini", "google"}:
            from langchain_google_genai import ChatGoogleGenerativeAI

            raw = ChatGoogleGenerativeAI(
                model=self._model(),
                google_api_key=self.settings.gemini_api_key,
            )
        elif provider == "openai":
            from langchain_openai import ChatOpenAI

            raw = ChatOpenAI(
                model=self._model(),
                api_key=self.settings.openai_api_key,
                temperature=0,
            )
        elif provider == "anthropic":
            from langchain_anthropic import ChatAnthropic

            raw = ChatAnthropic(
                model=self._model(),
                api_key=self.settings.anthropic_api_key,
                temperature=0,
            )
        else:
            raise RuntimeError(f"Unsupported ragas provider: {provider!r}")

        return LangchainLLMWrapper(raw)

    def _build_embeddings(self):
        from ragas.embeddings import LangchainEmbeddingsWrapper

        provider = self._provider()

        if provider in {"gemini", "google"}:
            from langchain_google_genai import GoogleGenerativeAIEmbeddings

            raw = GoogleGenerativeAIEmbeddings(
                model="models/gemini-embedding-001",
                google_api_key=self.settings.gemini_api_key,
            )
        elif provider == "openai":
            from langchain_openai import OpenAIEmbeddings

            raw = OpenAIEmbeddings(
                model="text-embedding-3-small",
                api_key=self.settings.openai_api_key,
            )
        else:
            raise RuntimeError(
                f"Ragas embeddings not configured for provider: {provider!r}"
            )

        return LangchainEmbeddingsWrapper(raw)

    def _build_metrics(self) -> dict:
        from ragas.metrics import (
            answer_relevancy as _answer_relevancy,
            context_precision as _context_precision,
            context_recall as _context_recall,
            faithfulness as _faithfulness,
        )

        try:
            _answer_relevancy.strictness = 1
        except Exception:
            pass

        return {
            "faithfulness": _faithfulness,
            "answer_relevancy": _answer_relevancy,
            "context_precision": _context_precision,
            "context_recall": _context_recall,
        }

    def _extract(self, result, name: str) -> float | None:
        """Pull a per-sample mean for one metric from a ragas result.

        Ragas 0.4.x exposes scores via ``result.to_pandas()``; older releases
        used dict access. Try the modern shape first, then fall back.
        """

        try:
            df = result.to_pandas()
            if name in df.columns:
                vals = [v for v in df[name].tolist() if v is not None]
                vals = [float(v) for v in vals]
                if vals:
                    return sum(vals) / len(vals)
        except Exception as exc:
            logger.warning("ragas_pandas_extract_failed", metric=name, error=str(exc))

        try:
            scores = getattr(result, "scores", None)
            if scores:
                vals = []
                for row in scores:
                    if isinstance(row, dict) and row.get(name) is not None:
                        vals.append(float(row[name]))
                if vals:
                    return sum(vals) / len(vals)
        except Exception:
            pass

        try:
            value = result.get(name) if hasattr(result, "get") else result[name]
            if value is not None:
                return float(value)
        except Exception:
            pass

        return None

    def _dump_once(self, result) -> None:
        if self._debug_done:
            return
        self._debug_done = True
        try:
            columns = list(result.to_pandas().columns)
            logger.warning("ragas_result_columns", columns=columns)
        except Exception:
            logger.warning(
                "ragas_result_shape_unknown",
                type=type(result).__name__,
                attrs=[a for a in dir(result) if not a.startswith("_")][:20],
            )

    def score(
        self,
        question: str,
        answer: str,
        contexts: list[str],
        ground_truth: str | None,
    ) -> RagasScores:
        if not self._ensure_initialized():
            return RagasScores(None, None, None, None)

        try:
            from ragas import EvaluationDataset, SingleTurnSample, evaluate
        except Exception as exc:
            logger.warning("ragas_import_failed", error=str(exc))
            return RagasScores(None, None, None, None)

        try:
            sample = SingleTurnSample(
                user_input=question,
                response=answer,
                retrieved_contexts=contexts,
                reference=ground_truth or "",
            )
            dataset = EvaluationDataset(samples=[sample])

            metrics = [
                self._metrics["faithfulness"],
                self._metrics["answer_relevancy"],
            ]
            if ground_truth:
                metrics.extend(
                    [
                        self._metrics["context_precision"],
                        self._metrics["context_recall"],
                    ]
                )

            result = evaluate(
                dataset,
                metrics=metrics,
                llm=self._llm,
                embeddings=self._embeddings,
            )

            faithfulness = self._extract(result, "faithfulness")
            answer_relevancy = self._extract(result, "answer_relevancy")
            context_precision = (
                self._extract(result, "context_precision") if ground_truth else None
            )
            context_recall = (
                self._extract(result, "context_recall") if ground_truth else None
            )

            if all(
                v is None
                for v in (faithfulness, answer_relevancy, context_precision, context_recall)
            ):
                self._dump_once(result)

            return RagasScores(
                faithfulness=faithfulness,
                answer_relevancy=answer_relevancy,
                context_precision=context_precision,
                context_recall=context_recall,
            )
        except Exception as exc:
            logger.warning("ragas_score_failed", error=str(exc))
            return RagasScores(None, None, None, None)


class FakeRagasScorer:
    """Deterministic offline scorer. NOT a real quality signal."""

    def score(
        self,
        question: str,
        answer: str,
        contexts: list[str],
        ground_truth: str | None,
    ) -> RagasScores:
        answer_tokens = set((answer or "").lower().split())
        context_tokens = set(" ".join(contexts).lower().split())
        question_tokens = set((question or "").lower().split())

        faithfulness = (
            len(answer_tokens & context_tokens) / len(answer_tokens)
            if answer_tokens
            else None
        )
        answer_relevancy = (
            len(question_tokens & answer_tokens) / len(question_tokens)
            if question_tokens
            else None
        )

        if ground_truth:
            gt_tokens = set(ground_truth.lower().split())
            context_precision = (
                len(answer_tokens & gt_tokens) / len(answer_tokens)
                if answer_tokens
                else None
            )
            context_recall = (
                len(answer_tokens & gt_tokens) / len(gt_tokens) if gt_tokens else None
            )
        else:
            context_precision = None
            context_recall = None

        return RagasScores(
            faithfulness=faithfulness,
            answer_relevancy=answer_relevancy,
            context_precision=context_precision,
            context_recall=context_recall,
        )
