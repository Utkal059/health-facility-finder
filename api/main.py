"""FastAPI application.

Run locally with:  uvicorn api.main:create_app --factory --reload
"""

from __future__ import annotations

import logging
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from api.cache import TtlCache
from api.config import Settings, get_settings
from api.db import create_pool
from api.errors import install_error_handlers
from api.rate_limit import SlidingWindowLimiter
from api.routes import facilities, masters, stats

DESCRIPTION = """
Search India's health facilities, as scraped from the public
[NHPR facility search](https://nhpr.abdm.gov.in/nhpr/v4/search/facility).

Every error has the same shape: `{"error": {"code", "message", "details"}}`.
"""


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    pool = create_pool(settings.database_url, settings.db_pool_size)

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        # Don't wait for the database: the API should still start (and /health
        # should say what's wrong) if Postgres is briefly unavailable.
        pool.open(wait=False)
        yield
        pool.close()

    app = FastAPI(
        title="Health Facility Finder API",
        version="1.0.0",
        description=DESCRIPTION,
        lifespan=lifespan,
    )
    app.state.settings = settings
    app.state.pool = pool
    app.state.search_limiter = SlidingWindowLimiter(settings.rate_limit_per_minute)
    app.state.cache = TtlCache()

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["GET"],
        allow_headers=["*"],
        expose_headers=["X-RateLimit-Limit", "X-RateLimit-Remaining", "Retry-After",
                        "X-Response-Time-Ms"],
        max_age=600,
    )

    @app.middleware("http")
    async def response_time(request: Request, call_next):
        started = time.perf_counter()
        response = await call_next(request)
        response.headers["X-Response-Time-Ms"] = f"{(time.perf_counter() - started) * 1000:.1f}"
        return response

    install_error_handlers(app)
    app.include_router(facilities.router)
    app.include_router(masters.router)
    app.include_router(stats.router)

    @app.get("/", include_in_schema=False)
    def index():
        return {"name": app.title, "docs": "/docs", "openapi": "/openapi.json", "health": "/health"}

    return app


logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
