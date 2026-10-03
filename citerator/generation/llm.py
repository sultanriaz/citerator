"""Provider-agnostic LLM clients for Citerator."""

from __future__ import annotations

import logging
import time
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Protocol

from citerator.config import Settings


@dataclass
class LLMResponse:
    text: str
    input_tokens: int | None = None
    output_tokens: int | None = None


class LLMClient(Protocol):
    def complete(self, system: str, user: str) -> LLMResponse:
        ...


class OpenAIClient:
    def __init__(self, api_key: str, model: str | None = None):
        from openai import OpenAI

        self.client = OpenAI(api_key=api_key)
        self.model = model or "gpt-4o-mini"

    def complete(self, system: str, user: str) -> LLMResponse:
        response = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            temperature=0,
        )
        usage = getattr(response, "usage", None)
        return LLMResponse(
            text=response.choices[0].message.content or "",
            input_tokens=getattr(usage, "prompt_tokens", None),
            output_tokens=getattr(usage, "completion_tokens", None),
        )


class AnthropicClient:
    def __init__(self, api_key: str, model: str | None = None):
        from anthropic import Anthropic

        self.client = Anthropic(api_key=api_key)
        self.model = model or "claude-3-haiku-20240307"

    def complete(self, system: str, user: str) -> LLMResponse:
        response = self.client.messages.create(
            model=self.model,
            max_tokens=1024,
            system=system,
            messages=[{"role": "user", "content": user}],
            temperature=0,
        )
        text = "".join(
            block.text for block in response.content if hasattr(block, "text")
        )
        usage = getattr(response, "usage", None)
        return LLMResponse(
            text=text,
            input_tokens=getattr(usage, "input_tokens", None),
            output_tokens=getattr(usage, "output_tokens", None),
        )


@contextmanager
def _silence_afc_warning():
    """Suppress google-genai's automatic-function-calling advisory.

    The SDK emits it whenever ``models.generate_content`` is called without
    going through ``Chat``. It does not affect correctness; the warning is
    purely stylistic.
    """
    target = logging.getLogger("google_genai.models")
    previous_level = target.level
    target.setLevel(logging.ERROR)
    try:
        yield
    finally:
        target.setLevel(previous_level)


class GeminiClient:
    """Google Gemini client using the new ``google-genai`` SDK.

    Transient server errors (429/5xx) are retried with exponential backoff.
    If the configured model returns 404, the client falls through to the next
    entry in ``fallback_models``. This makes the pipeline resilient to the
    routine model churn and capacity spikes on the Gemini API.
    """

    RETRYABLE_CODES = {429, 500, 502, 503, 504}
    MAX_ATTEMPTS = 4
    BASE_BACKOFF_SECONDS = 1.5
    FALLBACK_MODELS = ("gemini-flash-latest", "gemini-2.0-flash")

    def __init__(self, api_key: str, model: str | None = None):
        from google import genai

        self._genai = genai
        self.client = genai.Client(api_key=api_key)

        if model:
            self.models = [model] + [
                m for m in self.FALLBACK_MODELS if m != model
            ]
        else:
            self.models = list(self.FALLBACK_MODELS)

        self.last_model_used: str | None = None

    def complete(self, system: str, user: str) -> LLMResponse:
        from google.genai import errors as genai_errors

        last_error: Exception | None = None

        for model in self.models:
            for attempt in range(1, self.MAX_ATTEMPTS + 1):
                try:
                    response = self._call(model, system, user)
                    self.last_model_used = model
                    return self._to_response(response)
                except genai_errors.ClientError as exc:
                    status = getattr(exc, "status_code", None) or getattr(exc, "code", None)
                    if status == 404:
                        last_error = exc
                        break  # try next model
                    if status in self.RETRYABLE_CODES and attempt < self.MAX_ATTEMPTS:
                        last_error = exc
                        time.sleep(self.BASE_BACKOFF_SECONDS ** attempt)
                        continue
                    raise
                except genai_errors.ServerError as exc:
                    status = getattr(exc, "status_code", None) or getattr(exc, "code", None)
                    last_error = exc
                    if status in self.RETRYABLE_CODES and attempt < self.MAX_ATTEMPTS:
                        time.sleep(self.BASE_BACKOFF_SECONDS ** attempt)
                        continue
                    break  # exhausted retries for this model; try next

        if last_error is not None:
            raise last_error
        raise RuntimeError("GeminiClient.complete exhausted all models and attempts")

    def _call(self, model: str, system: str, user: str):
        with _silence_afc_warning():
            return self.client.models.generate_content(
                model=model,
                contents=user,
                config=self._genai.types.GenerateContentConfig(
                    system_instruction=system,
                    temperature=0,
                ),
            )

    def _to_response(self, response) -> LLMResponse:
        usage = getattr(response, "usage_metadata", None)
        return LLMResponse(
            text=response.text or "",
            input_tokens=getattr(usage, "prompt_token_count", None),
            output_tokens=getattr(usage, "candidates_token_count", None),
        )


class FakeLLMClient:
    """Deterministic offline LLM used by tests."""

    def __init__(self):
        self.invoked = False
        self.calls: list[tuple[str, str]] = []

    def complete(self, system: str, user: str) -> LLMResponse:
        import re

        self.invoked = True
        self.calls.append((system, user))

        match = re.search(r"Question:\s*(.+)", user)
        question = match.group(1).strip() if match else "the question"

        return LLMResponse(
            text=f"Echo: {question}\n\n[1]",
            input_tokens=len(user.split()),
            output_tokens=8,
        )


def get_llm_client(settings: Settings) -> LLMClient:
    provider = settings.llm_provider.lower()

    if provider == "openai":
        return OpenAIClient(settings.openai_api_key, settings.llm_model or None)
    if provider == "anthropic":
        return AnthropicClient(settings.anthropic_api_key, settings.llm_model or None)
    if provider in {"gemini", "google"}:
        return GeminiClient(settings.gemini_api_key, settings.llm_model or None)
    if provider == "fake":
        return FakeLLMClient()

    raise ValueError(f"Unknown llm_provider: {settings.llm_provider}")


