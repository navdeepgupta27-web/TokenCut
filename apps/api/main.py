"""TokenCut API entrypoint.

    uvicorn main:app --reload

Design notes worth knowing before you change anything here:

* The service boots with **no provider credentials**. Missing keys are not an
  error — the affected models report as unavailable and the OpenAI path (which
  needs no key) keeps working. The frontend is designed to stay useful when
  this backend is cold, throttled, or down entirely.
* Nothing here logs request bodies. Bodies are user prompts.
"""

from __future__ import annotations

import logging
import time
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from hmac import compare_digest

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.middleware.base import RequestResponseEndpoint
from starlette.responses import Response

from app.config import settings
from app.errors import register_exception_handlers
from app.infra.cache import close_cache, init_cache
from app.infra.logging import configure_logging
from app.routers import analysis, meta
from app.services.pricing import load_catalog
from app.services.tokenizer.openai_tiktoken import prewarm

log = logging.getLogger("tokencut")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    configure_logging()
    await init_cache()

    # Load the BPE tables now so the first user request isn't paying for a
    # cold, network-dependent tiktoken download.
    prewarm()

    catalog = load_catalog()
    if stale := catalog.stale_models():
        log.warning("startup_pricing_stale", extra={"models": stale})
    if not catalog.models:
        log.error("startup_pricing_empty", extra={"path": str(settings.pricing_catalog_path)})

    log.info(
        "startup_complete",
        extra={"env": settings.env, "models_priced": len(catalog.models)},
    )
    yield
    await close_cache()


app = FastAPI(
    title="TokenCut API",
    version="0.1.0",
    description=(
        "Token counting, prompt optimization, and cost analysis across LLM "
        "providers. Every count carries a `source` field describing how it was "
        "obtained; every cost carries the assumptions it was computed under."
    ),
    lifespan=lifespan,
    docs_url="/docs",
    openapi_url="/openapi.json",
)

# CORS. The frontend is on a different origin (Vercel) from the API (Render /
# Railway / Fly), so this is load-bearing, not boilerplate — a missing origin
# here is the single most common cause of a deployment that works locally and
# fails in production.
#
# allow_credentials stays False: the V1 API is unauthenticated and the V2 API
# will authenticate with a bearer token, not a cookie. Keeping it False is what
# makes a permissive origin list safe.
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization", "X-Request-Id"],
    expose_headers=["X-Request-Id", "Retry-After"],
    max_age=86_400,
)


# Paths reachable without the internal token. Health must stay open for the
# platform's own health check, and the schema is not sensitive.
_OPEN_PATHS = frozenset({"/", "/health", f"{settings.api_prefix}/health", "/docs", "/openapi.json"})


@app.middleware("http")
async def require_internal_token(
    request: Request, call_next: RequestResponseEndpoint
) -> Response:
    """Gate the API behind a shared secret, when one is configured.

    No token configured (the local-development default) means no gate — the
    service stays trivially runnable. But once deployed to a public URL, an
    ungated backend is an open proxy to the operator's Anthropic and Google
    quota, which someone will eventually find and drain.

    The browser never talks to this service directly; the Next.js BFF adds the
    header. So requiring it costs nothing in the real request path.
    """
    expected = settings.api_internal_token
    if expected and request.url.path not in _OPEN_PATHS:
        header = request.headers.get("authorization", "")
        scheme, _, presented = header.partition(" ")
        # compare_digest to avoid leaking the token through timing.
        if scheme.lower() != "bearer" or not compare_digest(presented, expected):
            request_id = request.headers.get("x-request-id") or uuid.uuid4().hex[:16]
            log.warning(
                "unauthorized_request",
                extra={"request_id": request_id, "path": request.url.path},
            )
            return JSONResponse(
                status_code=401,
                content={
                    "error": {
                        "code": "unauthorized",
                        "message": "Missing or invalid internal token.",
                        "details": {},
                        "request_id": request_id,
                    }
                },
            )
    return await call_next(request)


@app.middleware("http")
async def request_context(
    request: Request, call_next: RequestResponseEndpoint
) -> Response:
    request_id = request.headers.get("x-request-id") or uuid.uuid4().hex[:16]
    request.state.request_id = request_id
    started = time.perf_counter()

    response = await call_next(request)

    duration_ms = (time.perf_counter() - started) * 1000
    response.headers["X-Request-Id"] = request_id
    # Path, status, and duration only. Never the body, never the query string.
    log.info(
        "request",
        extra={
            "request_id": request_id,
            "method": request.method,
            "path": request.url.path,
            "status": response.status_code,
            "duration_ms": round(duration_ms, 1),
        },
    )
    return response


register_exception_handlers(app)

app.include_router(meta.router, prefix=settings.api_prefix)
app.include_router(analysis.router, prefix=settings.api_prefix)

# Unprefixed health check, for platform probes that don't know about /v1.
app.include_router(meta.router, include_in_schema=False)


@app.get("/", include_in_schema=False)
async def root() -> dict:
    return {
        "service": "tokencut-api",
        "version": app.version,
        "docs": "/docs",
        "health": f"{settings.api_prefix}/health",
    }
