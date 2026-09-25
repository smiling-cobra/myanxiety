"""Who has Plus, the paid tier.

Entitlement is one field on the user record, `plus_until`, a UTC instant, and it
is computed when read: a user has Plus while `plus_until` is in the future. There
is no "active" flag to keep in step with anything. A cancelled subscription is
never announced to the bot — Telegram simply stops renewing it — so access runs
out at the end of the period already paid for, with nothing to write.

`plus_source` records why the field was last moved (`subscription`,
`launch_trial` or `admin`), for the /plus status line and for analysis. It does
not change what the user gets.

**Reads never raise.** A failed read answers "free", the same rule as
`UsageService.consume_llm`: every Plus surface has a free path written and
tested, and the worst a paying user sees from a Mongo blip is one fixed
acknowledgement instead of a reply.
"""
from __future__ import annotations

import logging
from datetime import datetime

from repositories.user_repo import UserRepository
from services import time_utils

logger = logging.getLogger(__name__)

SOURCE_SUBSCRIPTION = 'subscription'
SOURCE_LAUNCH_TRIAL = 'launch_trial'
SOURCE_ADMIN = 'admin'


def plus_until(user: dict | None) -> datetime | None:
    """The stored end of Plus as an aware UTC instant, or None if there is none."""
    value = (user or {}).get('plus_until')
    return time_utils.as_utc(value) if isinstance(value, datetime) else None


def is_plus(user: dict | None, now: datetime | None = None) -> bool:
    """Pure: whether this user record has Plus at `now`. The scheduler, which already holds the record, calls this."""
    until = plus_until(user)
    return until is not None and until > (now or time_utils.now())


class PlanService:
    def __init__(self):
        self._users = UserRepository()

    def is_plus(self, telegram_id: int) -> bool:
        """Never raises; see the module docstring."""
        try:
            return is_plus(self._users.find(telegram_id))
        except Exception:
            logger.exception('Could not read the plan for user %s — treating them as free.', telegram_id)
            return False

    def extend(self, telegram_id: int, until: datetime, source: str) -> datetime:
        """Move `plus_until` forward to `until`, never back. Returns the stored end.

        A renewal that arrives late, a trial granted to a subscriber, or a
        duplicated payment update must never shorten what someone already has.
        Uses the non-upserting update: a payment for a deleted account must not
        recreate it.
        """
        until = time_utils.as_utc(until)
        current = plus_until(self._users.find(telegram_id))
        if current is not None and current >= until:
            return current
        self._users.update(telegram_id, plus_until=until, plus_source=source)
        return until

    def set_until(self, telegram_id: int, until: datetime, source: str) -> None:
        """Set `plus_until` outright, shorter or longer. For a refund and the admin switch only."""
        self._users.update(telegram_id, plus_until=time_utils.as_utc(until), plus_source=source)
