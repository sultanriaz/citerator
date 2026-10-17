"""FastAPI app factory for Citerator.

Phase 3-9 content is preserved. This version adds the governance layer:

  1. import citerator.governance -- registers the document-version hook
  2. AuditMiddleware registered inner to TracingMiddleware so it sees the
     bound trace_id when it writes its record
  3. governance_routes mounted alongside the existing routers

Audit is fail-closed when settings.audit_required is True: if the audit
record cannot be written, /query returns 503 rather than answering
unlogged.
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

import citerator.governance  # noqa: F401  -- registers the upsert hook
from citerator.api import (
    autotune_routes,
    calibration_routes,
    documents_routes,
    escalation_routes,
    eval_routes,
    feedback_routes,
    settings_routes,
)
from citerator.api.middleware.audit import AuditMiddleware
from citerator.api.rate_limit import RateLimitMiddleware
from citerator.api.routes import router
from citerator.api.streaming import router as streaming_router
from citerator.api.tracing_middleware import TracingMiddleware
from citerator.config import get_settings
from citerator.governance import routes as governance_routes
from citerator.observability.logging_config import configure_logging
from citerator.runtime_config.effective_settings import get_effective_settings


def _cors_origins(settings) -> list[str]:
    origins = set(settings.cors_origins or [])
    expanded = set(origins)
    for o in origins:
        if "://localhost" in o:
            expanded.add(o.replace("://localhost", "://127.0.0.1"))
        elif "://127.0.0.1" in o:
            expanded.add(o.replace("://127.0.0.1", "://localhost"))
    return sorted(expanded)


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings)

    app = FastAPI(title="Citerator API", version="0.1.0")

    # Order matters. Starlette wraps LIFO: last added is outermost.
    # Innermost -> outermost: Audit, Tracing, RateLimit, CORS.
    # Audit must be inner to Tracing so the trace_id is bound when Audit
    # writes its record.
    app.add_middleware(AuditMiddleware)
    app.add_middleware(TracingMiddleware)
    app.add_middleware(RateLimitMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_cors_origins(settings),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["X-Trace-Id", "Retry-After"],
    )

    app.dependency_overrides[get_settings] = get_effective_settings

    # Also register the effective-settings resolver itself. Routes and
    # tests that explicitly declare Depends(get_effective_settings) then
    # honour test-scoped overrides the same way Depends(get_settings) does.
    from citerator.runtime_config.effective_settings import (
        get_effective_settings as _get_effective_settings_symbol,
    )

    app.dependency_overrides[_get_effective_settings_symbol] = (
        get_effective_settings
    )

    app.include_router(router)
    app.include_router(documents_routes.router)
    app.include_router(eval_routes.router)
    app.include_router(settings_routes.router)
    app.include_router(feedback_routes.router)
    app.include_router(escalation_routes.router)
    app.include_router(calibration_routes.router)
    app.include_router(autotune_routes.router)
    app.include_router(governance_routes.router)
    app.include_router(streaming_router)
    return app


app = create_app()