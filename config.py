"""Startup configuration checks.

Without these, a deploy missing a secret fails somewhere else, and not clearly: a missing
`CLAUDE_API_KEY` raises from inside an import chain, a missing `TELEGRAM_TOKEN` fails in
the Telegram library's builder, and each restart reports only the first gap it hits.
`require_config` names every missing variable at once, before anything else is imported.
"""
from __future__ import annotations

import logging
import os
from collections.abc import Mapping

logger = logging.getLogger(__name__)

REQUIRED = ('TELEGRAM_TOKEN', 'CLAUDE_API_KEY', 'MONGODB_URI')


def missing_config(environ: Mapping[str, str] = os.environ) -> list[str]:
    """The required variables that are unset or blank. `.env` files leave blanks, e.g. `TELEGRAM_TOKEN=`."""
    return [name for name in REQUIRED if not (environ.get(name) or '').strip()]


def require_config(environ: Mapping[str, str] = os.environ) -> None:
    """Exit with one clear message if any required variable is missing."""
    missing = missing_config(environ)
    if missing:
        logger.critical(
            'Missing required configuration: %s. Set them in .env or the deploy secrets.', ', '.join(missing)
        )
        raise SystemExit(1)
