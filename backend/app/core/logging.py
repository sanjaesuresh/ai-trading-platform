"""Single place to configure backend logging."""

from __future__ import annotations

import logging

from app.core.config import get_settings

_configured = False


def configure_logging() -> None:
    """Configure root logging once, at the level from settings."""
    global _configured
    if _configured:
        return

    settings = get_settings()
    level = getattr(logging, settings.log_level.upper(), logging.INFO)
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
    )
    _configured = True


def get_logger(name: str) -> logging.Logger:
    configure_logging()
    return logging.getLogger(name)
