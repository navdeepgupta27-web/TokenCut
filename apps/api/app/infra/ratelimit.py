"""Per-client fixed-window rate limiting.

A cost control, not a security boundary: it exists so that one visitor cannot
burn the shared Anthropic/Google quota that every other visitor depends on.
It therefore **fails open** — if the backend is unreachable, requests pass.
"""

from __future__ import annotations

import logging

from fastapi import Request

from app.config import settings
from app.errors import RateLimited
from app.infra.cache import get_cache

log = logging.getLogger("tokencut.ratelimit")

_WINDOW_SECONDS = 60


def client_identity(request: Request) -> str:
    """Best-effort client identity.

    Behind Render/Railway/Vercel the peer address is the proxy, so prefer the
    leftmost X-Forwarded-For hop. This is spoofable; see the module docstring
    for why that is acceptable here.
    """
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


async def enforce(request: Request, *, cost: int = 1) -> None:
    """Raise ``RateLimited`` when the caller is over budget for this minute.

    ``cost`` lets expensive endpoints count for more than one unit — segment
    attribution fans out into many upstream calls and should not be as cheap
    as a plain local tokenize.
    """
    identity = client_identity(request)
    key = f"tc:rl:{identity}"

    cache = get_cache()
    count = 0
    for _ in range(cost):
        count = await cache.incr_window(key, _WINDOW_SECONDS)

    if count > settings.rate_limit_per_minute:
        log.info("rate_limited", extra={"identity_hash": hash(identity) & 0xFFFF, "count": count})
        raise RateLimited(
            "Too many requests. Slow down, or bring your own provider key for "
            "unmetered access.",
            retry_after=_WINDOW_SECONDS,
            details={"limit_per_minute": settings.rate_limit_per_minute},
        )
