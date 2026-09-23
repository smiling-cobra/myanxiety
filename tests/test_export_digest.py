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


def _digest(entries, tz=UTC, name='Sam', today=TODAY, window_days=30):
    return build_digest(name, entries, tz, today, window_days)


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

    def test_name_today_and_window_are_carried_through(self):
        digest = _digest([_e()], name=None, today=date(2026, 10, 1), window_days=14)
        assert (digest.name, digest.today, digest.window_days) == (None, date(2026, 10, 1), 14)


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
        assert [(t.tag, t.count) for t in digest.themes] == [('work', 2), ('sleep', 2)]

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


class TestDays:
    def test_entries_are_grouped_by_day_oldest_first(self):
        digest = _digest([
            _e('mon', when=NOW - timedelta(days=2)),
            _e('wed morning', when=NOW),
            _e('wed evening', when=NOW + timedelta(hours=8)),
        ])
        assert [d.day for d in digest.days] == [date(2026, 9, 28), date(2026, 9, 30)]
        assert [e.text for e in digest.days[1].entries] == ['wed morning', 'wed evening']

    def test_days_without_entries_are_absent(self):
        digest = _digest([_e(when=NOW - timedelta(days=5)), _e(when=NOW)])
        assert len(digest.days) == 2
        assert digest.day_count == 2

    def test_each_day_has_its_own_mood_range(self):
        digest = _digest([
            _e(mood=3, when=NOW),
            _e(mood=7, when=NOW + timedelta(hours=1)),
            _e(mood=8, when=NOW + timedelta(hours=2)),
        ])
        [day] = digest.days
        assert (day.mood.average, day.mood.lowest, day.mood.highest) == (6.0, 3, 8)

    def test_the_day_boundary_is_local_midnight(self):
        # In Tokyo (UTC+9), 14:30 and 15:30 UTC fall either side of midnight.
        digest = _digest(
            [_e('late', when=datetime(2026, 9, 29, 14, 30, tzinfo=UTC)),
             _e('early', when=datetime(2026, 9, 29, 15, 30, tzinfo=UTC))],
            tz=ZoneInfo('Asia/Tokyo'),
        )
        assert [(d.day, [e.text for e in d.entries]) for d in digest.days] == [
            (date(2026, 9, 29), ['late']),
            (date(2026, 9, 30), ['early']),
        ]


class TestThemeMoods:
    def test_each_theme_carries_the_average_mood_of_its_entries(self):
        digest = _digest([
            _e(mood=2, tags=['work']),
            _e(mood=4, tags=['work', 'sleep']),
            _e(mood=9, tags=['family']),
        ])
        themes = {t.tag: t for t in digest.themes}
        assert (themes['work'].count, themes['work'].average_mood) == (2, 3.0)
        assert themes['sleep'].average_mood == 4.0
        assert themes['family'].average_mood == 9.0

    def test_variants_count_towards_the_canonical_theme(self):
        digest = _digest([_e(mood=2, tags=['job']), _e(mood=6, tags=['Work'])])
        [theme] = digest.themes
        assert (theme.tag, theme.count, theme.average_mood) == ('work', 2, 4.0)


class TestLowest:
    def test_the_three_lowest_oldest_first(self):
        digest = _digest([
            _e('a', mood=5, when=NOW - timedelta(days=4)),
            _e('b', mood=2, when=NOW - timedelta(days=3)),
            _e('c', mood=8, when=NOW - timedelta(days=2)),
            _e('d', mood=1, when=NOW - timedelta(days=1)),
            _e('e', mood=3, when=NOW),
        ])
        assert [e.text for e in digest.lowest] == ['b', 'd', 'e']

    def test_ties_go_to_the_more_recent_entry(self):
        digest = _digest([
            _e('old', mood=2, when=NOW - timedelta(days=9)),
            _e('mid', mood=2, when=NOW - timedelta(days=5)),
            _e('new', mood=2, when=NOW - timedelta(days=1)),
            _e('newest', mood=2, when=NOW),
        ])
        assert [e.text for e in digest.lowest] == ['mid', 'new', 'newest']

    def test_fewer_entries_than_the_limit(self):
        assert [e.text for e in _digest([_e('only')]).lowest] == ['only']
