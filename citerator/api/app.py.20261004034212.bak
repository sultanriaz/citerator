"""FastAPI app factory for Citerator."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from citerator.api import documents_routes
from citerator.api.routes import router
from citerator.config import get_settings


def create_app() -> FastAPI:
    settings = get_settings()

    app = FastAPI(title="Citerator API", version="0.1.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(router)
    app.include_router(documents_routes.router)
    return app


app = create_app()
