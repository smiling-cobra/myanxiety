"""What the export says, before it is laid out. Pure: everything it uses is passed in.

This is the one place in the export that knows how an entry is stored. It
turns stored entries into local, typed `DigestEntry`s and works out the facts
the file reports, so a renderer only decides how they look.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, tzinfo

from services import time_utils
from services.tags import normalise_tags, tag_counts

_TOP_THEMES = 5


@dataclass(frozen=True)
class DigestEntry:
    moment: datetime
    """When it was written, in the user's timezone."""
    mood: int
    text: str
    tags: tuple[str, ...]
    """Read through the current tag vocabulary."""
    flagged: bool


@dataclass(frozen=True)
class MoodStats:
    average: float
    lowest: int
    highest: int


@dataclass(frozen=True)
class ExportDigest:
    name: str | None
    today: date
    first_day: date
    last_day: date
    entries: tuple[DigestEntry, ...]
    """Oldest first."""
    flagged: tuple[DigestEntry, ...]
    """The entries the user marked to raise in session, oldest first."""
    day_count: int
    """Distinct local days with at least one entry."""
    mood: MoodStats
    themes: tuple[tuple[str, int], ...]
    """The most common themes with the number of entries each came up in."""


def build_digest(name: str | None, entries: list, tz: tzinfo, today: date) -> ExportDigest:
    """The digest of stored `entries`, which must be non-empty and oldest first,
    as `JournalService` returns them."""
    if not entries:
        raise ValueError('an export digest needs at least one entry')

    local = tuple(_digest_entry(entry, tz) for entry in entries)
    scores = [e.mood for e in local]
    return ExportDigest(
        name=name,
        today=today,
        first_day=local[0].moment.date(),
        last_day=local[-1].moment.date(),
        entries=local,
        flagged=tuple(e for e in local if e.flagged),
        day_count=len({e.moment.date() for e in local}),
        mood=MoodStats(average=sum(scores) / len(scores), lowest=min(scores), highest=max(scores)),
        themes=tuple(tag_counts(entries, _TOP_THEMES)),
    )


def _digest_entry(entry: dict, tz: tzinfo) -> DigestEntry:
    return DigestEntry(
        moment=time_utils.to_local(entry['created_at'], tz),
        mood=entry['mood_score'],
        text=entry['text'],
        tags=tuple(normalise_tags(entry.get('tags') or [])),
        flagged=bool(entry.get('flagged_for_session')),
    )
