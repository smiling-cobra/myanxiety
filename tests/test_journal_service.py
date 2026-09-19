"""Tests for JournalService — streak logic, weekly windows and stats.

Streak rules under test:
  - First entry ever       → streak = 1
  - Second entry same day  → streak unchanged
  - Entry the next day     → streak + 1
  - Entry after a gap > 1d → streak resets to 1

"Day" means the user's local day, not the UTC day. The TestTimezoneBoundaries
class pins that distinction down: the two cases there pass in a UTC-keyed
implementation only by accident of the tester's own offset.
"""
from datetime import date, datetime, timedelta, timezone
from unittest.mock import patch

import pytest

from repositories.user_repo import UserRepository
from services.journal_service import JournalService

USER = 111111
UTC = timezone.utc


@pytest.fixture
def svc():
    return JournalService()


def _set_timezone(name: str) -> None:
    UserRepository().save({'telegram_id': USER, 'timezone': name, 'onboarded': True})


def _save_at(svc: JournalService, moment: datetime, mood: int = 5, text: str = "entry") -> None:
    """Save an entry as if the clock read this exact UTC instant."""
    with patch('services.time_utils.now', return_value=moment):
        svc.save_entry(USER, mood, text)


def _save_on(svc: JournalService, d: date, mood: int = 5, text: str = "entry") -> None:
    """Save an entry as if it happened at 10:00 UTC on the given date."""
    _save_at(svc, datetime(d.year, d.month, d.day, 10, 0, tzinfo=UTC), mood, text)


class TestStreakLogic:
    def test_first_entry_streak_is_one(self, svc):
        svc.save_entry(USER, 7, "first")
        assert svc.get_stats(USER)['streak'] == 1

    def test_same_day_does_not_increment(self, svc):
        svc.save_entry(USER, 7, "morning")
        svc.save_entry(USER, 5, "evening")
        assert svc.get_stats(USER)['streak'] == 1

    def test_consecutive_day_increments(self, svc):
        _save_on(svc, date(2026, 3, 26))
        _save_on(svc, date(2026, 3, 27))
        assert svc.get_stats(USER)['streak'] == 2

    def test_gap_resets_streak_to_one(self, svc):
        _save_on(svc, date(2026, 3, 25))
        _save_on(svc, date(2026, 3, 27))  # skipped the 26th
        assert svc.get_stats(USER)['streak'] == 1

    def test_streak_accumulates_over_multiple_days(self, svc):
        for day in range(24, 28):  # 24, 25, 26, 27
            _save_on(svc, date(2026, 3, day))
        assert svc.get_stats(USER)['streak'] == 4

    def test_streak_resets_after_long_gap_then_rebuilds(self, svc):
        _save_on(svc, date(2026, 3, 1))
        _save_on(svc, date(2026, 3, 10))  # gap → reset to 1
        _save_on(svc, date(2026, 3, 11))  # consecutive → 2
        assert svc.get_stats(USER)['streak'] == 2


class TestFirstOfDay:
    """save_entry reports whether the entry is the day's check-in or a later note."""

    def test_first_entry_ever_is_first_of_day(self, svc):
        assert _save_at_returning(svc, datetime(2026, 3, 26, 9, 0, tzinfo=UTC)) is True

    def test_second_entry_same_day_is_not(self, svc):
        _save_at(svc, datetime(2026, 3, 26, 9, 0, tzinfo=UTC))
        assert _save_at_returning(svc, datetime(2026, 3, 26, 20, 0, tzinfo=UTC)) is False

    def test_next_day_is_first_again(self, svc):
        _save_at(svc, datetime(2026, 3, 26, 9, 0, tzinfo=UTC))
        assert _save_at_returning(svc, datetime(2026, 3, 27, 9, 0, tzinfo=UTC)) is True

    def test_the_day_is_the_users_own(self, svc):
        # Niue is UTC-11: both instants are the 26th locally, across two UTC days.
        _set_timezone('Pacific/Niue')
        _save_at(svc, datetime(2026, 3, 26, 22, 0, tzinfo=UTC))
        assert _save_at_returning(svc, datetime(2026, 3, 27, 9, 0, tzinfo=UTC)) is False


def _save_at_returning(svc: JournalService, moment: datetime) -> bool:
    with patch('services.time_utils.now', return_value=moment):
        return svc.save_entry(USER, 5, "entry")


class TestTimezoneBoundaries:
    """Day boundaries follow the user, not UTC."""

    def test_one_utc_day_spanning_two_local_days_increments(self, svc):
        # Kiritimati is UTC+14, so a single UTC day straddles two local days.
        _set_timezone('Pacific/Kiritimati')
        _save_at(svc, datetime(2026, 3, 26, 9, 0, tzinfo=UTC))   # local 26th, 23:00
        _save_at(svc, datetime(2026, 3, 26, 11, 0, tzinfo=UTC))  # local 27th, 01:00
        assert svc.get_stats(USER)['streak'] == 2

    def test_two_utc_days_inside_one_local_day_does_not_increment(self, svc):
        # Niue is UTC-11, so one local day straddles two UTC days.
        _set_timezone('Pacific/Niue')
        _save_at(svc, datetime(2026, 3, 26, 22, 0, tzinfo=UTC))  # local 26th, 11:00
        _save_at(svc, datetime(2026, 3, 27, 9, 0, tzinfo=UTC))   # local 26th, 22:00
        assert svc.get_stats(USER)['streak'] == 1

    def test_missing_timezone_falls_back_to_utc(self, svc):
        # No user record at all — the pre-existing UTC behaviour is preserved.
        _save_at(svc, datetime(2026, 3, 26, 9, 0, tzinfo=UTC))
        _save_at(svc, datetime(2026, 3, 26, 11, 0, tzinfo=UTC))
        assert svc.get_stats(USER)['streak'] == 1

    def test_malformed_timezone_falls_back_to_utc(self, svc):
        _set_timezone('Not/ARealZone')
        _save_at(svc, datetime(2026, 3, 26, 9, 0, tzinfo=UTC))
        _save_at(svc, datetime(2026, 3, 26, 11, 0, tzinfo=UTC))
        assert svc.get_stats(USER)['streak'] == 1

    def test_stored_timestamps_stay_utc(self, svc):
        _set_timezone('Pacific/Kiritimati')
        moment = datetime(2026, 3, 26, 9, 0, tzinfo=UTC)
        _save_at(svc, moment)
        stored = svc.get_recent_entries(USER)[0]['created_at']
        if stored.tzinfo is None:  # what pymongo hands back in production
            stored = stored.replace(tzinfo=UTC)
        assert stored == moment


class TestCheckedInToday:
    """Whether today's check-in has happened, in the user's own day."""

    def _checked_in_at(self, svc, moment: datetime, tz_name: str = None) -> bool:
        with patch('services.time_utils.now', return_value=moment):
            return svc.checked_in_today(USER, tz_name)

    def test_never_checked_in(self, svc):
        assert self._checked_in_at(svc, datetime(2026, 3, 26, 12, 0, tzinfo=UTC)) is False

    def test_checked_in_earlier_today(self, svc):
        _save_at(svc, datetime(2026, 3, 26, 9, 0, tzinfo=UTC))
        assert self._checked_in_at(svc, datetime(2026, 3, 26, 20, 0, tzinfo=UTC)) is True

    def test_yesterday_does_not_count(self, svc):
        _save_at(svc, datetime(2026, 3, 25, 9, 0, tzinfo=UTC))
        assert self._checked_in_at(svc, datetime(2026, 3, 26, 9, 0, tzinfo=UTC)) is False

    def test_local_midnight_starts_a_new_day(self, svc):
        # Kiritimati is UTC+14: 09:00 UTC is 23:00 local, 11:00 UTC is 01:00 the next day.
        _set_timezone('Pacific/Kiritimati')
        _save_at(svc, datetime(2026, 3, 26, 9, 0, tzinfo=UTC))
        assert self._checked_in_at(svc, datetime(2026, 3, 26, 11, 0, tzinfo=UTC)) is False

    def test_explicit_timezone_argument_is_used(self, svc):
        # No user record: without the argument this would be read as UTC, and
        # 23:00 UTC on the 25th would be "yesterday".
        _save_at(svc, datetime(2026, 3, 25, 23, 0, tzinfo=UTC))  # 26th, 08:00 in Tokyo
        moment = datetime(2026, 3, 26, 3, 0, tzinfo=UTC)          # 26th, 12:00 in Tokyo
        assert self._checked_in_at(svc, moment, 'Asia/Tokyo') is True
        assert self._checked_in_at(svc, moment) is False

    def test_is_user_scoped(self, svc):
        with patch('services.time_utils.now', return_value=datetime(2026, 3, 26, 9, 0, tzinfo=UTC)):
            svc.save_entry(999, 5, "someone else's")
        assert self._checked_in_at(svc, datetime(2026, 3, 26, 12, 0, tzinfo=UTC)) is False


class TestWeeklyEntries:
    def _frozen(self, svc, now, **kwargs):
        with patch('services.time_utils.now', return_value=now):
            return svc.get_weekly_entries(USER, **kwargs)

    def test_returns_entries_within_last_7_days(self, svc):
        today = datetime.now(UTC).date()
        _save_on(svc, today)
        _save_on(svc, today - timedelta(days=6))
        assert len(svc.get_weekly_entries(USER)) == 2

    def test_excludes_entries_older_than_7_days(self, svc):
        today = datetime.now(UTC).date()
        _save_on(svc, today)
        _save_on(svc, today - timedelta(days=8))
        assert len(svc.get_weekly_entries(USER)) == 1

    def test_returns_entries_in_ascending_order(self, svc):
        today = datetime.now(UTC).date()
        _save_on(svc, today - timedelta(days=2), mood=3)
        _save_on(svc, today, mood=7)
        entries = svc.get_weekly_entries(USER)
        assert entries[0]['mood_score'] == 3
        assert entries[1]['mood_score'] == 7

    def test_returns_empty_for_new_user(self, svc):
        assert svc.get_weekly_entries(USER) == []

    def test_is_user_scoped(self, svc):
        other = 999999
        _save_on(svc, datetime.now(UTC).date())
        assert svc.get_weekly_entries(other) == []

    def test_window_starts_at_local_midnight(self, svc):
        # Kiritimati is UTC+14. With the clock at 2026-03-26 00:00 UTC it is
        # already 14:00 on the 26th locally, so the window opens at local
        # midnight on the 20th — 2026-03-19 10:00 UTC.
        _set_timezone('Pacific/Kiritimati')
        _save_at(svc, datetime(2026, 3, 19, 12, 0, tzinfo=UTC), mood=7)  # local 20th → in
        _save_at(svc, datetime(2026, 3, 19, 8, 0, tzinfo=UTC), mood=3)   # local 19th → out

        entries = self._frozen(svc, datetime(2026, 3, 26, 0, 0, tzinfo=UTC))
        assert [e['mood_score'] for e in entries] == [7]

    def test_explicit_timezone_argument_is_used(self, svc):
        # The scheduler passes the timezone it already holds; no user record here.
        _save_at(svc, datetime(2026, 3, 19, 12, 0, tzinfo=UTC), mood=7)
        _save_at(svc, datetime(2026, 3, 19, 8, 0, tzinfo=UTC), mood=3)

        now = datetime(2026, 3, 26, 0, 0, tzinfo=UTC)
        entries = self._frozen(svc, now, user_timezone='Pacific/Kiritimati')
        assert [e['mood_score'] for e in entries] == [7]


class TestStats:
    def test_total_counts_all_entries(self, svc):
        svc.save_entry(USER, 5, "one")
        svc.save_entry(USER, 7, "two")
        assert svc.get_stats(USER)['total'] == 2

    def test_average_mood_is_correct(self, svc):
        svc.save_entry(USER, 4, "low")
        svc.save_entry(USER, 8, "high")
        assert svc.get_stats(USER)['avg_mood'] == 6.0

    def test_empty_user_returns_zeros(self, svc):
        stats = svc.get_stats(USER)
        assert stats['streak'] == 0
        assert stats['total'] == 0
        assert stats['avg_mood'] == 0.0

    def test_stats_are_user_scoped(self, svc):
        other = 999999
        svc.save_entry(USER, 8, "mine")
        svc.save_entry(other, 3, "theirs")
        assert svc.get_stats(USER)['total'] == 1
        assert svc.get_stats(other)['total'] == 1


class TestSessionFlag:
    def test_no_entries_is_none(self, svc):
        assert svc.toggle_session_flag(USER) is None

    def test_flags_only_the_latest_entry(self, svc):
        from repositories.entry_repo import EntryRepository
        _save_at(svc, datetime(2026, 3, 25, 10, 0, tzinfo=UTC), text='older')
        _save_at(svc, datetime(2026, 3, 26, 10, 0, tzinfo=UTC), text='newer')

        entry = svc.toggle_session_flag(USER)

        assert entry['text'] == 'newer'
        assert entry['flagged_for_session'] is True
        stored = {e['text']: e.get('flagged_for_session') for e in EntryRepository().find_recent(USER)}
        assert stored == {'newer': True, 'older': None}

    def test_a_second_toggle_unflags(self, svc):
        from repositories.entry_repo import EntryRepository
        _save_at(svc, datetime(2026, 3, 26, 10, 0, tzinfo=UTC))
        svc.toggle_session_flag(USER)
        assert svc.toggle_session_flag(USER)['flagged_for_session'] is False
        assert EntryRepository().find_recent(USER)[0]['flagged_for_session'] is False

    def test_is_user_scoped(self, svc):
        _save_at(svc, datetime(2026, 3, 26, 10, 0, tzinfo=UTC))
        assert svc.toggle_session_flag(999) is None
