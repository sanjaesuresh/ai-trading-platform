"""ARQ queue module: connection settings parse correctly from a URL.

Enqueuing against a live Redis is a manual integration step, not a unit test.
"""

from __future__ import annotations

from arq.connections import RedisSettings


def test_redis_settings_parses_url() -> None:
    """RedisSettings.from_dsn splits host, port, and database correctly."""
    settings = RedisSettings.from_dsn("redis://host:6379/2")
    assert settings.host == "host"
    assert settings.port == 6379
    assert settings.database == 2
