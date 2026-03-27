"""Tests for JournalService — streak logic and stats aggregation.

Streak rules under test:
  - First entry ever       → streak = 1
  - Second entry same day  → streak unchanged
  - Entry the next day     → streak + 1
  - Entry after a gap > 1d → streak resets to 1
"""
from datetime import date, datetime
from unittest.mock import patch

import pytest

from services.journal_service import JournalService

USER = 111111


@pytest.fixture
def svc():
    return JournalService()


def _save_on(svc: JournalService, d: date, mood: int = 5, text: str = "entry") -> None:
    """Save an entry as if it happened on the given date."""
    dt = datetime(d.year, d.month, d.day, 10, 0)
    with patch('services.journal_service.datetime') as mock_dt:
        mock_dt.utcnow.return_value = dt
        svc.save_entry(USER, mood, text)


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
