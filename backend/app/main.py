"""FastAPI application entry point.

Registers routers, configures CORS, and manages lifespan (http client + store).
"""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .api.routes_experiments import router as experiments_router
from .api.routes_future import router_evolve, router_skills
from .api.routes_gaps import router as gaps_router
from .api.routes_literature import router as literature_router
from .api.routes_skills import router as skills_router
from .config import get_settings
from .services.experiment import ensure_seed_skill
from .services.http import close_client
from .storage.store import get_store


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage application lifespan: init store on startup, cleanup on shutdown."""
    # Startup
    settings = get_settings()
    store = get_store()  # ensure DB is initialized
    ensure_seed_skill(store)
    yield
    # Shutdown
    await close_client()
    store.close()


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    settings = get_settings()

    app = FastAPI(
        title="ResearchLoop Evo API",
        description="Evidence-grounded autonomous research agent",
        version="0.1.0",
        lifespan=lifespan,
    )

    # CORS
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Routers
    app.include_router(literature_router)
    app.include_router(gaps_router)
    app.include_router(experiments_router)
    app.include_router(skills_router)
    app.include_router(router_evolve)
    app.include_router(router_skills)

    @app.get("/")
    async def root():
        return {
            "name": "ResearchLoop Evo API",
            "version": "0.1.0",
            "status": "Phase 1 complete",
            "docs": "/docs",
        }

    @app.get("/api/health")
    async def health():
        """Health check endpoint."""
        from datetime import datetime, timezone

        return {
            "status": "ok",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "version": "0.1.0",
        }

    return app


app = create_app()
