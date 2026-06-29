"""Settings: redis_url field has a safe default."""

from __future__ import annotations

from app.core.config import get_settings


def test_settings_have_redis_url_default() -> None:
    assert get_settings().redis_url.startswith("redis://")
