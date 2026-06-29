"""FastAPI application factory.

Mounts routers, configures CORS for the frontend, creates tables on startup,
and wires logging. Simulated-only research tool — not financial advice.
"""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import backtests, evaluation, health, strategies
from app.core.config import get_settings
from app.core.database import create_all_tables
from app.core.logging import configure_logging, get_logger

log = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging()
    create_all_tables()
    log.info("Startup complete: tables ready.")
    yield


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title=settings.app_name,
        version="0.1.0",
        description="Simulated trend-following backtesting research API. Not financial advice.",
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(health.router)
    app.include_router(backtests.router)
    app.include_router(strategies.router)
    app.include_router(evaluation.router)
    return app


app = create_app()
