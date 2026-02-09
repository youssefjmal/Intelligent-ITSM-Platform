"""Simple logging setup for the application."""

from __future__ import annotations

import logging
import os


def setup_logging(level: str | None = None) -> None:
    if logging.getLogger().handlers:
        return

    level_name = (level or os.getenv("LOG_LEVEL", "INFO")).upper()
    logging.basicConfig(
        level=level_name,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )
