"""FastAPI app factory for Citerator.

Phase 3-6 content is preserved. Phase 6 added the dependency_override and
rate-limit middleware. Phase 7 adds, and only adds:

  1. configure_logging(settings) at build time -- sets up structlog with
     contextvars merging and the log-forwarding processor
  2. import + registration of TracingMiddleware (per-request /query trace)
  3. import + include_router for feedback_routes
  4. import + include_router for escalation_routes

Middleware registration order (later = outermost):
  TracingMiddleware  -> innermost, wraps only the app
  RateLimitMiddleware -> middle
  CORSMiddleware     -> outermost, handles preflight

Rate limiting therefore runs before tracing, so a rate-limited /query
never generates a trace_id. That is deliberate: a burst shouldn't be
able to spam a tracing backend.
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from citerator.api import (
    documents_routes,
    escalation_routes,
    eval_routes,
    feedback_routes,
    settings_routes,
)
from citerator.api.rate_limit import RateLimitMiddleware
from citerator.api.routes import router
from citerator.api.tracing_middleware import TracingMiddleware
from citerator.config import get_settings
from citerator.observability.logging_config import configure_logging
from citerator.runtime_config.effective_settings import get_effective_settings


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings)

    app = FastAPI(title="Citerator API", version="0.1.0")

    app.add_middleware(TracingMiddleware)
    app.add_middleware(
        RateLimitMiddleware, limit=settings.rate_limit_requests_per_minute
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.dependency_overrides[get_settings] = get_effective_settings

    app.include_router(router)
    app.include_router(documents_routes.router)
    app.include_router(eval_routes.router)
    app.include_router(settings_routes.router)
    app.include_router(feedback_routes.router)
    app.include_router(escalation_routes.router)
    return app


app = create_app()
