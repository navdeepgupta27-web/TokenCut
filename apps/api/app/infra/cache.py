"""Token-count cache.

This is the component that makes the free tier survivable. Claude and Gemini
counts cost a keyed, rate-limited upstream call; the same prompt text is
counted over and over as a user tweaks the tail of it.

Keys are ``sha256(text) + ":" + model_id``. Values are integers. No plaintext
is ever stored — the cache is safe to run on shared infrastructure.

Redis when ``REDIS_URL`` is set; an in-process TTL map otherwise, so local
development and a single-instance free-tier deploy both work with no extra
service.
"""

from __future__ import annotations

import hashlib
import logging
import time
from typing import Protocol

from app.config import settings

log = logging.getLogger("tokencut.cache")


def count_key(text: str, model: str) -> str:
    """Cache key for a token count.

    The model id is part of the key and must stay that way: Claude tokenizers
    changed within the 4.x line, so `claude-opus-5` and `claude-sonnet-4-6`
    genuinely produce different counts for identical text.
    """
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    return f"tc:count:{digest}:{model}"


class CacheBackend(Protocol):
    name: str

    async def get_int(self, key: str) -> int | None: ...
    async def set_int(self, key: str, value: int, ttl: int) -> None: ...
    async def incr_window(self, key: str, window_seconds: int) -> int: ...
    async def close(self) -> None: ...


class InMemoryCache:
    """Single-process TTL map. Adequate for dev and one-instance deploys."""

    name = "memory"

    def __init__(self, max_entries: int = 50_000) -> None:
        self._data: dict[str, tuple[int, float]] = {}
        self._max = max_entries

    def _sweep(self) -> None:
        now = time.monotonic()
        expired = [k for k, (_, exp) in self._data.items() if exp <= now]
        for k in expired:
            self._data.pop(k, None)
        # Crude bound: if still oversized, drop the soonest-to-expire entries.
        if len(self._data) > self._max:
            overflow = len(self._data) - self._max
            oldest = sorted(self._data.items(), key=lambda kv: kv[1][1])[:overflow]
            for k, _ in oldest:
                self._data.pop(k, None)

    async def get_int(self, key: str) -> int | None:
        entry = self._data.get(key)
        if entry is None:
            return None
        value, expires_at = entry
        if expires_at <= time.monotonic():
            self._data.pop(key, None)
            return None
        return value

    async def set_int(self, key: str, value: int, ttl: int) -> None:
        if len(self._data) >= self._max:
            self._sweep()
        self._data[key] = (value, time.monotonic() + ttl)

    async def incr_window(self, key: str, window_seconds: int) -> int:
        bucket = int(time.time() // window_seconds)
        wkey = f"{key}:{bucket}"
        current = await self.get_int(wkey) or 0
        current += 1
        await self.set_int(wkey, current, window_seconds + 1)
        return current

    async def close(self) -> None:
        self._data.clear()


class RedisCache:
    name = "redis"

    def __init__(self, client) -> None:  # noqa: ANN001 — redis.asyncio.Redis
        self._r = client

    async def get_int(self, key: str) -> int | None:
        try:
            raw = await self._r.get(key)
        except Exception as exc:  # cache failures must never fail a request
            log.warning("cache_get_failed", extra={"exc_type": type(exc).__name__})
            return None
        if raw is None:
            return None
        try:
            return int(raw)
        except (TypeError, ValueError):
            return None

    async def set_int(self, key: str, value: int, ttl: int) -> None:
        try:
            await self._r.set(key, value, ex=ttl)
        except Exception as exc:
            log.warning("cache_set_failed", extra={"exc_type": type(exc).__name__})

    async def incr_window(self, key: str, window_seconds: int) -> int:
        bucket = int(time.time() // window_seconds)
        wkey = f"{key}:{bucket}"
        try:
            pipe = self._r.pipeline()
            pipe.incr(wkey)
            pipe.expire(wkey, window_seconds + 1)
            count, _ = await pipe.execute()
            return int(count)
        except Exception as exc:
            # Fail open. A broken rate limiter must not take down the service;
            # it is a cost control, not a security boundary.
            log.warning("ratelimit_backend_failed", extra={"exc_type": type(exc).__name__})
            return 0

    async def close(self) -> None:
        try:
            await self._r.aclose()
        except Exception:  # pragma: no cover — best-effort shutdown
            pass


_backend: CacheBackend | None = None


async def init_cache() -> CacheBackend:
    global _backend
    if _backend is not None:
        return _backend

    if settings.redis_url:
        try:
            import redis.asyncio as aioredis

            client = aioredis.from_url(
                settings.redis_url,
                encoding="utf-8",
                decode_responses=True,
                socket_connect_timeout=3,
            )
            await client.ping()
            _backend = RedisCache(client)
            log.info("cache_backend_selected", extra={"backend": "redis"})
            return _backend
        except Exception as exc:
            log.warning(
                "redis_unavailable_falling_back",
                extra={"exc_type": type(exc).__name__},
            )

    _backend = InMemoryCache()
    log.info("cache_backend_selected", extra={"backend": "memory"})
    return _backend


def get_cache() -> CacheBackend:
    if _backend is None:
        raise RuntimeError("cache not initialised; call init_cache() during startup")
    return _backend


async def close_cache() -> None:
    global _backend
    if _backend is not None:
        await _backend.close()
        _backend = None
