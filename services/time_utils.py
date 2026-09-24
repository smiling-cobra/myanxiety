"""Shared time helpers.

Entries are stored as UTC instants. Anything the user reads as a day — a streak,
a weekly window, a date label in history — is resolved against their own
timezone, so a check-in just before local midnight belongs to the day they
actually lived through rather than the day UTC happened to be on.
"""
from __future__ import annotations

import logging
import re
from datetime import date, datetime, timezone, tzinfo
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)

UTC = timezone.utc


def now() -> datetime:
    """The clock seam for day-based logic — tests patch this, not `datetime`."""
    return datetime.now(UTC)


def as_utc(value: datetime) -> datetime:
    """Read a stored timestamp back as an aware UTC instant.

    pymongo returns naive datetimes unless the client is built with
    `tz_aware=True`, and the suite swaps in a mongomock client that never sees
    that setting. Everything written here is UTC, so a naive value is labelled
    rather than converted.
    """
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def resolve_timezone(name: str = None, telegram_id: int = None) -> tzinfo:
    """Resolve an IANA timezone name, falling back to UTC.

    Presentation and streak rules are not safety decisions, so an absent or
    malformed timezone degrades to the previous UTC-keyed behaviour rather than
    dropping the check-in. The scheduler deliberately does not share this
    policy: a bad timezone there must suppress the send, not guess at UTC and
    message someone in the middle of their night.
    """
    if not name:
        return UTC

    try:
        return ZoneInfo(name)
    except Exception:
        logger.warning(
            'Invalid timezone %r for user %s — falling back to UTC for day boundaries.',
            name, telegram_id,
        )
        return UTC


def to_local(value: datetime, tz: tzinfo) -> datetime:
    """Render a stored timestamp in the user's timezone."""
    return as_utc(value).astimezone(tz)


def local_today(name: str = None, telegram_id: int = None) -> date:
    """The user's current local date, with `resolve_timezone`'s UTC fallback."""
    return now().astimezone(resolve_timezone(name, telegram_id)).date()


_REMINDER_TIME = re.compile(r'^\d{2}:\d{2}$')


def parse_reminder_time(text: str) -> str | None:
    """A typed reminder time as stored `HH:MM`, or None if it isn't one.

    Onboarding and /settings both take a reminder time from free text, so they
    share this rather than each keeping a copy of the rule.
    """
    text = (text or '').strip()
    if not _REMINDER_TIME.match(text):
        return None
    hour, minute = int(text[:2]), int(text[3:])
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        return None
    return text
