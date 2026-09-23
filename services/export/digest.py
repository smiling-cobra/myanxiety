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
_LOWEST_ENTRIES = 3


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
class DayDigest:
    """One local day that has at least one entry: the daily check-in and any notes after it."""
    day: date
    entries: tuple[DigestEntry, ...]
    """Oldest first."""
    mood: MoodStats


@dataclass(frozen=True)
class Theme:
    tag: str
    count: int
    """The number of entries it came up in."""
    average_mood: float
    """The average mood of those entries. Paired with the count, it is what a
    reader needs to tell a theme that comes up from one that weighs."""


@dataclass(frozen=True)
class ExportDigest:
    name: str | None
    today: date
    window_days: int
    """How many local days the export covers, ending today."""
    first_day: date
    last_day: date
    entries: tuple[DigestEntry, ...]
    """Oldest first."""
    days: tuple[DayDigest, ...]
    """The entries grouped by local day, oldest first. Days without entries are absent."""
    flagged: tuple[DigestEntry, ...]
    """The entries the user marked to raise in session, oldest first."""
    lowest: tuple[DigestEntry, ...]
    """The lowest-rated entries, oldest first. Ties go to the more recent entry."""
    mood: MoodStats
    themes: tuple[Theme, ...]
    """The most common themes, most frequent first."""

    @property
    def day_count(self) -> int:
        """Distinct local days with at least one entry."""
        return len(self.days)


def build_digest(name: str | None, entries: list, tz: tzinfo, today: date, window_days: int) -> ExportDigest:
    """The digest of stored `entries`, which must be non-empty and oldest first,
    as `JournalService` returns them."""
    if not entries:
        raise ValueError('an export digest needs at least one entry')

    local = tuple(_digest_entry(entry, tz) for entry in entries)
    return ExportDigest(
        name=name,
        today=today,
        window_days=window_days,
        first_day=local[0].moment.date(),
        last_day=local[-1].moment.date(),
        entries=local,
        days=_days(local),
        flagged=tuple(e for e in local if e.flagged),
        lowest=_lowest(local),
        mood=_mood_stats(local),
        themes=_themes(entries, local),
    )


def _days(entries: tuple[DigestEntry, ...]) -> tuple[DayDigest, ...]:
    by_day: dict[date, list[DigestEntry]] = {}
    for entry in entries:
        by_day.setdefault(entry.moment.date(), []).append(entry)
    return tuple(
        DayDigest(day=day, entries=tuple(group), mood=_mood_stats(group))
        for day, group in sorted(by_day.items())
    )


def _lowest(entries: tuple[DigestEntry, ...]) -> tuple[DigestEntry, ...]:
    # Lowest mood first, and the more recent of two equal scores, because the
    # recent one is the one still likely to be live in the session.
    picked = sorted(entries, key=lambda e: (e.mood, -e.moment.timestamp()))[:_LOWEST_ENTRIES]
    return tuple(sorted(picked, key=lambda e: e.moment))


def _themes(stored: list, local: tuple[DigestEntry, ...]) -> tuple[Theme, ...]:
    # Ranked by `tag_counts` so the export agrees with /stats and the weekly
    # summary. The mood is read from the digest entries, whose tags went
    # through the same normalisation.
    themes = []
    for tag, count in tag_counts(stored, _TOP_THEMES):
        scores = [e.mood for e in local if tag in e.tags]
        themes.append(Theme(tag=tag, count=count, average_mood=sum(scores) / len(scores)))
    return tuple(themes)


def _mood_stats(entries) -> MoodStats:
    scores = [e.mood for e in entries]
    return MoodStats(average=sum(scores) / len(scores), lowest=min(scores), highest=max(scores))


def _digest_entry(entry: dict, tz: tzinfo) -> DigestEntry:
    return DigestEntry(
        moment=time_utils.to_local(entry['created_at'], tz),
        mood=entry['mood_score'],
        text=entry['text'],
        tags=tuple(normalise_tags(entry.get('tags') or [])),
        flagged=bool(entry.get('flagged_for_session')),
    )
