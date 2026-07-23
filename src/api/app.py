from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware

from src.api.dependencies import ApplicationContainer, default_container
from src.api.routes import downloads, evaluations, pages, reviews, runs, suggestions

STATIC_DIRECTORY = Path(__file__).parent / "static"


def create_app(container: ApplicationContainer | None = None) -> FastAPI:
    app = FastAPI(title="Customer Service Hallucination Detection")
    app.state.container = container or default_container()
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=["localhost", "127.0.0.1", "[::1]"])
    app.mount("/static", StaticFiles(directory=STATIC_DIRECTORY), name="static")
    app.include_router(pages.router)
    app.include_router(runs.router)
    app.include_router(reviews.router)
    app.include_router(evaluations.router)
    app.include_router(suggestions.router)
    app.include_router(downloads.router)
    return app


app = create_app()
