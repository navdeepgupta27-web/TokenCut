from __future__ import annotations

import pytest


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture(autouse=True)
def _isolate_caches():
    """Reset the lru_cached data loaders between tests that tweak settings."""
    from app.services import pricing
    from app.services.tokenizer import estimator

    pricing.load_catalog.cache_clear()
    estimator.load_calibration.cache_clear()
    yield
    pricing.load_catalog.cache_clear()
    estimator.load_calibration.cache_clear()
