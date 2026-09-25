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


def admin_ids(environ: Mapping[str, str] = os.environ) -> frozenset[int]:
    """The Telegram ids in `ADMIN_TELEGRAM_IDS` (comma-separated), allowed the admin commands.

    Optional: unset means nobody. A malformed id is skipped with a warning rather
    than failing boot, because nothing a user relies on depends on it.
    """
    ids = set()
    for part in (environ.get('ADMIN_TELEGRAM_IDS') or '').split(','):
        part = part.strip()
        if not part:
            continue
        try:
            ids.add(int(part))
        except ValueError:
            logger.warning('Ignoring malformed id %r in ADMIN_TELEGRAM_IDS.', part)
    return frozenset(ids)
