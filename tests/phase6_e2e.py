"""Phase 6 end-to-end verification.

Exercises the real FastAPI app via TestClient:
  - auth is required on /settings/*
  - hot-reload: PUT /settings/pipeline is reflected by get_effective_settings
    and by re-reads of /settings/pipeline
  - validation: floor>=threshold, rerank>retrieve, bad chunking, missing
    collection, embedding_model tampering — all 422
  - API key: masked on GET, full on POST regenerate, new key actually
    authenticates, old key is rejected
  - reset restores baseline
  - preview-threshold runs real retrieval/rerank/confidence (stubbed) and
    never calls the LLM
  - rate limiter: /health exempt, over-limit returns 429 + Retry-After

Run directly:  python tests/phase6_e2e.py
Exit code 0 if all checks pass, 1 if any fail, 2 on unexpected error.
"""

from __future__ import annotations

import sys
import tempfile
import traceback
import uuid
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


# ============================================================
# Tiny test harness
# ============================================================
class Harness:
    def __init__(self) -> None:
        self.passed = 0
        self.failed = 0
        self.failures: list[str] = []

    def section(self, name: str) -> None:
        print(f"\n=== {name} ===")

    def check(self, label: str, condition: bool, detail: str = "") -> None:
        if condition:
            self.passed += 1
            print(f"  [PASS] {label}")
        else:
            self.failed += 1
            self.failures.append(label)
            suffix = f"  -> {detail}" if detail else ""
            print(f"  [FAIL] {label}{suffix}")

    def summary(self) -> int:
        print("\n=== Summary ===")
        print(f"  Passed: {self.passed}")
        print(f"  Failed: {self.failed}")
        if self.failures:
            print("  Failed checks:")
            for f in self.failures:
                print(f"    - {f}")
        return 0 if self.failed == 0 else 1


# ============================================================
# Fake settings environment
# ============================================================
@contextmanager
def fake_env(tmp_path: Path, api_key: str, rate_limit: int):
    """Route every Settings lookup in runtime_config to a temp-DB Settings."""
    from citerator.config import Settings

    fake = Settings(
        runtime_config_db_path=(tmp_path / "runtime.sqlite").as_posix(),
        api_key=api_key,
        rate_limit_requests_per_minute=rate_limit,
    )

    with patch(
        "citerator.runtime_config.overrides.get_settings", return_value=fake
    ), patch(
        "citerator.runtime_config.effective_settings.get_settings", return_value=fake
    ):
        yield fake


# ============================================================
# The end-to-end run
# ============================================================
def run() -> int:
    h = Harness()

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        primary_key = "test-key-1234"

        with fake_env(tmp, api_key=primary_key, rate_limit=10000):
            from fastapi.testclient import TestClient
            from citerator.api.app import app
            from citerator.runtime_config.effective_settings import (
                get_effective_settings,
            )

            client = TestClient(app)
            headers = {"X-API-Key": primary_key}

            # ---------------------------------------------------------
            h.section("1. Auth is required")
            r = client.get("/settings/pipeline")
            h.check(
                "no key -> 401/403/422",
                r.status_code in (401, 403, 422),
                f"got {r.status_code}",
            )

            # ---------------------------------------------------------
            h.section("2. Baseline pipeline read")
            r = client.get("/settings/pipeline", headers=headers)
            h.check("GET 200", r.status_code == 200, f"got {r.status_code}")
            body = r.json() if r.status_code == 200 else {}
            baseline_top_k = body.get("top_k_retrieve")
            h.check("has top_k_retrieve", baseline_top_k is not None)
            h.check(
                "has is_override flags",
                isinstance(body.get("is_override"), dict)
                and len(body["is_override"]) == 6,
            )
            h.check(
                "nothing overridden initially",
                all(v is False for v in body.get("is_override", {}).values()),
            )

            # ---------------------------------------------------------
            h.section("3. Hot-reload: PUT pipeline reaches effective settings")
            new_top_k = (baseline_top_k or 5) + 7
            r = client.put(
                "/settings/pipeline",
                json={"top_k_retrieve": new_top_k},
                headers=headers,
            )
            h.check(
                "PUT 200",
                r.status_code == 200,
                f"got {r.status_code} {r.text}",
            )
            h.check(
                "response reflects new value",
                r.json().get("top_k_retrieve") == new_top_k,
            )

            r = client.get("/settings/pipeline", headers=headers)
            h.check(
                "GET reflects new value",
                r.json().get("top_k_retrieve") == new_top_k,
            )
            h.check(
                "is_override true for top_k_retrieve",
                r.json()["is_override"]["top_k_retrieve"] is True,
            )

            # Proof that the dependency-override mechanism actually works:
            eff = get_effective_settings()
            h.check(
                "get_effective_settings reflects override",
                eff.top_k_retrieve == new_top_k,
            )

            # And that the base object is NOT mutated
            from citerator.config import get_settings as base_get_settings

            h.check(
                "base get_settings object not mutated",
                base_get_settings().top_k_retrieve != new_top_k,
            )

            # ---------------------------------------------------------
            h.section("4. Validation: confidence_floor >= threshold rejected")
            r = client.put(
                "/settings/pipeline",
                json={"confidence_floor": 0.95, "confidence_threshold": 0.85},
                headers=headers,
            )
            h.check(
                "422 on floor >= threshold",
                r.status_code == 422,
                f"got {r.status_code} {r.text}",
            )
            h.check(
                "error mentions confidence_floor",
                "confidence_floor" in r.text.lower(),
            )

            # ---------------------------------------------------------
            h.section("5. Validation: top_k_rerank > top_k_retrieve rejected")
            r = client.put(
                "/settings/pipeline",
                json={"top_k_retrieve": 5, "top_k_rerank": 10},
                headers=headers,
            )
            h.check(
                "422 on rerank > retrieve",
                r.status_code == 422,
                f"got {r.status_code} {r.text}",
            )

            # ---------------------------------------------------------
            h.section("6. Validation: unknown chunking strategy rejected")
            r = client.put(
                "/settings/pipeline",
                json={"active_chunking_strategy": "bogus"},
                headers=headers,
            )
            h.check(
                "422 on bad chunking",
                r.status_code == 422,
                f"got {r.status_code} {r.text}",
            )

            # ---------------------------------------------------------
            h.section("7. Chunking switch rejected if collection missing")
            with patch(
                "citerator.api.settings_routes._collection_exists",
                return_value=False,
            ):
                r = client.put(
                    "/settings/pipeline",
                    json={"active_chunking_strategy": "semantic"},
                    headers=headers,
                )
            h.check(
                "422 when collection missing",
                r.status_code == 422,
                f"got {r.status_code} {r.text}",
            )
            h.check(
                "error points at ingestion",
                "ingest" in r.text.lower() or "no indexed" in r.text.lower(),
            )

            # And it works when the collection exists
            with patch(
                "citerator.api.settings_routes._collection_exists",
                return_value=True,
            ):
                r = client.put(
                    "/settings/pipeline",
                    json={"active_chunking_strategy": "semantic"},
                    headers=headers,
                )
            h.check(
                "200 when collection exists",
                r.status_code == 200,
                f"got {r.status_code} {r.text}",
            )

            # ---------------------------------------------------------
            h.section("8. Models read: embedding_model is read-only")
            r = client.get("/settings/models", headers=headers)
            h.check("GET 200", r.status_code == 200)
            body = r.json()
            h.check(
                "embedding_model.editable is False",
                body["embedding_model"].get("editable") is False,
            )
            h.check(
                "embedding_model.reason mentions re-ingestion",
                "re-ingestion" in body["embedding_model"].get("reason", "").lower(),
            )
            h.check("has cost_privacy_note", isinstance(body.get("cost_privacy_note"), str))

            # ---------------------------------------------------------
            h.section("9. Models PUT rejects embedding_model")
            r = client.put(
                "/settings/models",
                json={"embedding_model": "sneaky-change"},
                headers=headers,
            )
            h.check(
                "422 on embedding_model PUT",
                r.status_code == 422,
                f"got {r.status_code} {r.text}",
            )

            r = client.put(
                "/settings/models",
                json={"llm_provider": "anthropic", "llm_model": "claude-3-sonnet"},
                headers=headers,
            )
            h.check(
                "200 on valid models PUT",
                r.status_code == 200,
                f"got {r.status_code} {r.text}",
            )
            h.check(
                "llm_provider updated",
                r.json().get("llm_provider") == "anthropic",
            )

            # ---------------------------------------------------------
            h.section("10. GET /settings/api never leaks the full key")
            r = client.get("/settings/api", headers=headers)
            h.check("GET 200", r.status_code == 200)
            body = r.json()
            masked = body["api_key_masked"]
            h.check("masked contains asterisks", "*" in masked)
            h.check("masked ends with 1234", masked.endswith("1234"))
            h.check(
                "full key not present in response",
                primary_key not in r.text,
            )
            h.check(
                "endpoints list is non-empty",
                isinstance(body.get("endpoints"), list) and len(body["endpoints"]) > 0,
            )
            h.check("rate_limit block present", "rate_limit" in body)
            h.check(
                "every endpoint has curl example",
                all("curl" in ep for ep in body["endpoints"]),
            )

            # ---------------------------------------------------------
            h.section("11. Regenerate: new key works, old key rejected")
            r = client.post("/settings/api/regenerate", headers=headers)
            h.check("POST regenerate 200", r.status_code == 200)
            body = r.json()
            new_key = body.get("api_key")
            h.check(
                "returned a full key",
                isinstance(new_key, str) and len(new_key) >= 20,
            )
            h.check("response has warning", "warning" in body)

            r = client.get(
                "/settings/pipeline", headers={"X-API-Key": primary_key}
            )
            h.check(
                "old key rejected after regeneration",
                r.status_code in (401, 403, 422),
                f"got {r.status_code}",
            )

            r = client.get(
                "/settings/pipeline", headers={"X-API-Key": new_key}
            )
            h.check(
                "new key authenticates",
                r.status_code == 200,
                f"got {r.status_code}",
            )

            r = client.get("/settings/api", headers={"X-API-Key": new_key})
            h.check(
                "subsequent GET masks the new key",
                new_key not in r.json()["api_key_masked"],
            )

            # Use the new key for the rest of the run
            headers = {"X-API-Key": new_key}

            # ---------------------------------------------------------
            h.section("12. Reset restores baseline")
            client.put(
                "/settings/pipeline",
                json={"top_k_retrieve": 99},
                headers=headers,
            )
            r = client.post(
                "/settings/reset", json={"section": "pipeline"}, headers=headers
            )
            h.check("POST reset 200", r.status_code == 200)
            h.check(
                "top_k_retrieve != 99 after reset",
                r.json().get("top_k_retrieve") != 99,
            )

            r = client.post(
                "/settings/reset", json={"section": "bogus"}, headers=headers
            )
            h.check(
                "422 on invalid section",
                r.status_code == 422,
                f"got {r.status_code}",
            )

            # ---------------------------------------------------------
            h.section("13. preview-threshold runs real retrieval, no LLM")
            with patch(
                "citerator.evaluation.questions.load_questions",
                return_value=[
                    {"question": "What is AML?"},
                    {"question": "What is KYC?"},
                    {"question": "What is CDD?"},
                ],
            ), patch(
                "citerator.retrieval.search.search", return_value=[]
            ) as mock_search, patch(
                "citerator.retrieval.rerank.rerank", return_value=[]
            ) as mock_rerank, patch(
                "citerator.retrieval.confidence.band",
                return_value="insufficient",
            ) as mock_band:
                r = client.post(
                    "/settings/pipeline/preview-threshold",
                    json={"confidence_threshold": 0.8, "confidence_floor": 0.5},
                    headers=headers,
                )
            h.check(
                "preview-threshold 200",
                r.status_code == 200,
                f"got {r.status_code} {r.text}",
            )
            body = r.json()
            h.check("total == 3", body.get("total") == 3)
            h.check("insufficient == 3", body.get("insufficient") == 3)
            h.check(
                "note explains fresh scoring",
                "not derived from stored" in body.get("note", ""),
            )
            h.check("retrieval.search was called", mock_search.called)
            h.check("rerank was called", mock_rerank.called)
            h.check("confidence.band was called", mock_band.called)

            # ---------------------------------------------------------
            h.section("14. Rate limiter")
            rate_key = f"rate-{uuid.uuid4().hex[:10]}"
            with fake_env(tmp, api_key=rate_key, rate_limit=3):
                rate_headers = {"X-API-Key": rate_key}

                # /health is exempt — burn 10 requests
                for _ in range(10):
                    r = client.get("/health")
                h.check(
                    "health exempt from rate limit",
                    r.status_code == 200,
                    f"got {r.status_code}",
                )

                # Now hammer /settings/pipeline
                ok = 0
                saw_429 = False
                for _ in range(6):
                    r = client.get("/settings/pipeline", headers=rate_headers)
                    if r.status_code == 429:
                        saw_429 = True
                        h.check(
                            "429 has Retry-After header",
                            "Retry-After" in r.headers,
                        )
                        h.check(
                            "429 body has error=rate_limited",
                            r.json().get("error") == "rate_limited",
                        )
                        h.check(
                            "429 body has retry_after_seconds",
                            isinstance(
                                r.json().get("retry_after_seconds"), int
                            ),
                        )
                        break
                    if r.status_code == 200:
                        ok += 1

                h.check(f"under-limit requests succeeded ({ok})", ok >= 1)
                h.check("limit was actually enforced", saw_429)

    return h.summary()


if __name__ == "__main__":
    try:
        sys.exit(run())
    except Exception:
        traceback.print_exc()
        sys.exit(2)
