"""Application settings.

All configuration is read here, once, via pydantic-settings. No module in the
codebase may read ``os.environ`` directly — import ``settings`` instead.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field, ValidationInfo, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Repo root: .../tokencut/  (this file is apps/api/app/config.py)
REPO_ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ---- service -------------------------------------------------------
    env: str = Field(default="development", description="development | staging | production")
    log_level: str = Field(default="INFO")
    api_prefix: str = "/v1"

    # ---- CORS ----------------------------------------------------------
    # Comma-separated in the environment. Never "*" in production — the API
    # is keyed in V2 and a wildcard origin plus credentials is a real hole.
    cors_origins: str = Field(default="http://localhost:3000")

    # ---- provider credentials ------------------------------------------
    # Absent keys are not an error. The affected models are reported as
    # unavailable via GET /v1/models and degrade to the estimator.
    anthropic_api_key: str | None = None
    google_api_key: str | None = None

    # ---- infra ----------------------------------------------------------
    redis_url: str | None = None
    cache_ttl_seconds: int = 86_400  # 24h; keys are content hashes, so this is safe

    # ---- limits ----------------------------------------------------------
    max_text_bytes: int = 400_000
    rate_limit_per_minute: int = 60
    rate_limit_burst: int = 20
    upstream_timeout_seconds: float = 10.0

    # Segment-level attribution fans out into one upstream call per segment.
    # Hard-cap it or a single paste can cost hundreds of API calls.
    max_segments_for_attribution: int = 40

    # ---- data files --------------------------------------------------------
    pricing_catalog_path: Path = REPO_ROOT / "data" / "pricing" / "catalog.json"
    calibration_path: Path = REPO_ROOT / "data" / "calibration" / "estimator.json"

    # ---- staleness guard ---------------------------------------------------
    # Mirrors the CI check. Prices older than this are still served, but every
    # response carries a `pricing_stale` warning the UI must render.
    pricing_max_age_days: int = 30

    @field_validator("cors_origins")
    @classmethod
    def _no_wildcard_in_prod(cls, v: str, info: ValidationInfo) -> str:
        if v.strip() == "*" and (info.data or {}).get("env") == "production":
            raise ValueError("cors_origins may not be '*' in production")
        return v

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def is_production(self) -> bool:
        return self.env == "production"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
