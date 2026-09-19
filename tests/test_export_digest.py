"""Tests for the export digest — what the file says, as values. Pure: no database, no Markdown."""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from services.export.digest import build_digest

UTC = timezone.utc
NOW = datetime(2026, 9, 30, 12, 0, tzinfo=UTC)
TODAY = date(2026, 9, 30)


def _e(text='x', mood=5, when=NOW, tags=None, flagged=None) -> dict:
    entry = {'text': text, 'mood_score': mood, 'created_at': when, 'tags': tags or []}
    if flagged is not None:
        entry['flagged_for_session'] = flagged
    return entry


def _digest(entries, tz=UTC, name='Sam', today=TODAY):
    return build_digest(name, entries, tz, today)


class TestEntries:
    def test_fields_are_read_from_the_stored_entry(self):
        [entry] = _digest([_e('some words', mood=3, flagged=True)]).entries
        assert (entry.text, entry.mood, entry.flagged) == ('some words', 3, True)

    def test_order_is_kept(self):
        digest = _digest([_e('first', when=NOW - timedelta(days=1)), _e('second')])
        assert [e.text for e in digest.entries] == ['first', 'second']

    def test_times_are_local(self):
        digest = _digest([_e(when=datetime(2026, 9, 29, 23, 30, tzinfo=UTC))], tz=ZoneInfo('Europe/Berlin'))
        assert digest.entries[0].moment.replace(tzinfo=None) == datetime(2026, 9, 30, 1, 30)

    def test_naive_stored_times_are_read_as_utc(self):
        digest = _digest([_e(when=datetime(2026, 9, 29, 23, 30))], tz=ZoneInfo('Europe/Berlin'))
        assert digest.entries[0].moment.hour == 1

    def test_tags_are_read_through_the_vocabulary(self):
        [entry] = _digest([_e(tags=['Work', 'work stress', 'insomnia'])]).entries
        assert entry.tags == ('work', 'sleep')

    def test_a_missing_flag_is_not_flagged(self):
        [entry] = _digest([_e()]).entries
        assert entry.flagged is False

    def test_an_empty_export_is_refused(self):
        with pytest.raises(ValueError):
            _digest([])


class TestSpan:
    def test_first_and_last_day_are_local(self):
        # Kiritimati is UTC+14: noon UTC is already the next day there.
        digest = _digest(
            [_e(when=NOW - timedelta(days=3)), _e(when=NOW)],
            tz=ZoneInfo('Pacific/Kiritimati'),
        )
        assert (digest.first_day, digest.last_day) == (date(2026, 9, 28), date(2026, 10, 1))

    def test_name_and_today_are_carried_through(self):
        digest = _digest([_e()], name=None, today=date(2026, 10, 1))
        assert (digest.name, digest.today) == (None, date(2026, 10, 1))


class TestSummary:
    def test_counts_distinct_local_days_and_mood(self):
        digest = _digest([
            _e(mood=2, when=NOW - timedelta(days=2)),
            _e(mood=6, when=NOW - timedelta(days=1)),
            _e(mood=7, when=NOW),
            _e(mood=9, when=NOW + timedelta(minutes=5)),
        ])
        assert len(digest.entries) == 4
        assert digest.day_count == 3
        assert (digest.mood.average, digest.mood.lowest, digest.mood.highest) == (6.0, 2, 9)

    def test_days_are_counted_in_local_time(self):
        # 23:30 and 00:30 UTC are two UTC days but one Berlin day (01:30 and 02:30).
        entries = [
            _e(when=datetime(2026, 9, 29, 23, 30, tzinfo=UTC)),
            _e(when=datetime(2026, 9, 30, 0, 30, tzinfo=UTC)),
        ]
        assert _digest(entries, tz=ZoneInfo('Europe/Berlin')).day_count == 1

    def test_themes_are_normalised_and_counted_per_entry(self):
        digest = _digest([
            _e(tags=['job', 'insomnia']),
            _e(tags=['Work', 'work stress']),
            _e(tags=['sleep']),
        ])
        assert digest.themes == (('work', 2), ('sleep', 2))

    def test_legacy_fallback_prose_is_not_a_theme(self):
        digest = _digest([_e(tags=["I'm having trouble responding right now. Please try again later."])])
        assert digest.themes == ()
        assert digest.entries[0].tags == ()


class TestFlagged:
    def test_only_flagged_entries_in_order(self):
        digest = _digest([
            _e('one', when=NOW - timedelta(days=2), flagged=True),
            _e('two', when=NOW - timedelta(days=1), flagged=False),
            _e('three'),
            _e('four', when=NOW + timedelta(minutes=1), flagged=True),
        ])
        assert [e.text for e in digest.flagged] == ['one', 'four']

    def test_none_flagged(self):
        assert _digest([_e(), _e(flagged=False)]).flagged == ()
