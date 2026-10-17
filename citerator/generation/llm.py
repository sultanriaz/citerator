"""Provider-agnostic LLM clients for Citerator.

Every client implements complete() for one-shot generation and stream() for
token-by-token generation. Streaming is a native capability of each SDK;
the fallback path (when a client doesn't implement stream) yields the full
response in a single chunk so callers don't have to branch.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterator, Protocol

from citerator.config import Settings


@dataclass
class LLMResponse:
    text: str
    input_tokens: int | None = None
    output_tokens: int | None = None


class LLMClient(Protocol):
    def complete(self, system: str, user: str) -> LLMResponse:
        ...

    def stream(self, system: str, user: str) -> Iterator[str]:
        ...


def _fallback_stream(client: "LLMClient", system: str, user: str) -> Iterator[str]:
    """Yield the full response as a single chunk when streaming isn't
    implemented. Callers see a coherent stream either way."""

    response = client.complete(system, user)
    if response.text:
        yield response.text


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

    def stream(self, system: str, user: str) -> Iterator[str]:
        stream = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            temperature=0,
            stream=True,
        )
        for chunk in stream:
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta
            text = getattr(delta, "content", None)
            if text:
                yield text


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

    def stream(self, system: str, user: str) -> Iterator[str]:
        with self.client.messages.stream(
            model=self.model,
            max_tokens=1024,
            system=system,
            messages=[{"role": "user", "content": user}],
            temperature=0,
        ) as stream:
            for text in stream.text_stream:
                if text:
                    yield text


class GeminiClient:
    RETRYABLE_CODES = {429, 500, 502, 503, 504}
    MAX_ATTEMPTS = 4
    BASE_BACKOFF_SECONDS = 1.5
    FALLBACK_MODELS = (
        "gemini-3.5-flash-lite",
        "gemini-2.5-flash",
        "gemini-flash-latest",
    )

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

    def _build_config(self, system: str):
        return self._genai.types.GenerateContentConfig(
            system_instruction=system,
            temperature=0,
        )

    def complete(self, system: str, user: str) -> LLMResponse:
        import time
        from google.genai import errors as genai_errors

        last_error: Exception | None = None
        for model in self.models:
            for attempt in range(1, self.MAX_ATTEMPTS + 1):
                try:
                    with self._silence_afc_warning():
                        response = self.client.models.generate_content(
                            model=model,
                            contents=user,
                            config=self._build_config(system),
                        )
                    self.last_model_used = model
                    usage = getattr(response, "usage_metadata", None)
                    return LLMResponse(
                        text=response.text or "",
                        input_tokens=getattr(usage, "prompt_token_count", None),
                        output_tokens=getattr(
                            usage, "candidates_token_count", None
                        ),
                    )
                except genai_errors.ClientError as exc:
                    status = getattr(exc, "status_code", None) or getattr(
                        exc, "code", None
                    )
                    last_error = exc
                    if status == 404:
                        break
                    if status in self.RETRYABLE_CODES and attempt < self.MAX_ATTEMPTS:
                        time.sleep(self.BASE_BACKOFF_SECONDS ** attempt)
                        continue
                    raise
                except genai_errors.ServerError as exc:
                    last_error = exc
                    if attempt < self.MAX_ATTEMPTS:
                        time.sleep(self.BASE_BACKOFF_SECONDS ** attempt)
                        continue
                    break
        if last_error is not None:
            raise last_error
        raise RuntimeError("GeminiClient.complete exhausted all models")

    def stream(self, system: str, user: str) -> Iterator[str]:
        import time
        from google.genai import errors as genai_errors

        last_error: Exception | None = None
        for model in self.models:
            for attempt in range(1, self.MAX_ATTEMPTS + 1):
                try:
                    with self._silence_afc_warning():
                        stream = self.client.models.generate_content_stream(
                            model=model,
                            contents=user,
                            config=self._build_config(system),
                        )
                        self.last_model_used = model
                        for chunk in stream:
                            text = getattr(chunk, "text", None)
                            if text:
                                yield text
                        return
                except genai_errors.ClientError as exc:
                    status = getattr(exc, "status_code", None) or getattr(
                        exc, "code", None
                    )
                    last_error = exc
                    if status == 404:
                        break
                    if status in self.RETRYABLE_CODES and attempt < self.MAX_ATTEMPTS:
                        time.sleep(self.BASE_BACKOFF_SECONDS ** attempt)
                        continue
                    raise
                except genai_errors.ServerError as exc:
                    last_error = exc
                    if attempt < self.MAX_ATTEMPTS:
                        time.sleep(self.BASE_BACKOFF_SECONDS ** attempt)
                        continue
                    break
        if last_error is not None:
            raise last_error
        raise RuntimeError("GeminiClient.stream exhausted all models")

    def _silence_afc_warning(self):
        import logging

        class _Silence:
            def __enter__(self):
                self.logger = logging.getLogger("google_genai.models")
                self.prev = self.logger.level
                self.logger.setLevel(logging.ERROR)

            def __exit__(self, *args):
                self.logger.setLevel(self.prev)

        return _Silence()


class FakeLLMClient:
    """Deterministic offline LLM used by tests. Streams word-by-word so the
    SSE path can be exercised without a network."""

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

    def stream(self, system: str, user: str) -> Iterator[str]:
        response = self.complete(system, user)
        words = response.text.split(" ")
        for i, word in enumerate(words):
            suffix = " " if i < len(words) - 1 else ""
            yield word + suffix


def get_llm_client(settings: Settings) -> LLMClient:
    provider = settings.llm_provider.lower()

    if provider == "openai":
        return OpenAIClient(settings.openai_api_key, settings.llm_model or None)
    if provider == "anthropic":
        return AnthropicClient(
            settings.anthropic_api_key, settings.llm_model or None
        )
    if provider in {"gemini", "google"}:
        return GeminiClient(settings.gemini_api_key, settings.llm_model or None)
    if provider == "fake":
        return FakeLLMClient()

    raise ValueError(f"Unknown llm_provider: {settings.llm_provider}")


def stream_with_fallback(
    client: LLMClient, system: str, user: str
) -> Iterator[str]:
    """Call client.stream() if available, else fall back to complete()."""

    stream_fn = getattr(client, "stream", None)
    if callable(stream_fn):
        try:
            yield from stream_fn(system, user)
            return
        except (AttributeError, NotImplementedError):
            pass
    yield from _fallback_stream(client, system, user)