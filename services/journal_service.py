from __future__ import annotations

from datetime import datetime, time, timedelta, tzinfo

from repositories.entry_repo import EntryRepository
from repositories.streak_repo import StreakRepository
from repositories.user_repo import UserRepository
from services import time_utils

_WEEK_DAYS = 7
MIN_ENTRIES_FOR_WEEKLY_SUMMARY = 3


class JournalService:
    """Entry storage, streak rules and stats aggregation.

    Timestamps are stored as UTC instants. Day-based rules — whether a check-in
    counts as "today", which entries fall inside "this week" — are evaluated in
    the user's own timezone. See `services/time_utils.py`.
    """

    def __init__(self):
        self._entries = EntryRepository()
        self._streaks = StreakRepository()
        self._users = UserRepository()

    def save_entry(self, telegram_id: int, mood_score: int, text: str, tags: list = None) -> None:
        now = time_utils.now()
        entry = {
            'telegram_id': telegram_id,
            'mood_score': mood_score,
            'text': text,
            'tags': tags or [],
            'created_at': now,
        }
        self._entries.save(entry)
        # Same instant for both, so an entry can never land on one side of a day
        # boundary and its own streak update on the other.
        self._update_streak(telegram_id, now)

    def get_recent_entries(self, telegram_id: int, limit: int = 7) -> list:
        return self._entries.find_recent(telegram_id, limit)

    def get_weekly_entries(self, telegram_id: int, user_timezone: str = None) -> list:
        """Entries from the last 7 local calendar days, today included."""
        return self.get_entries_for_days(telegram_id, _WEEK_DAYS, user_timezone)

    def get_entries_for_days(self, telegram_id: int, days: int, user_timezone: str = None) -> list:
        """Entries from the last `days` local calendar days, today included, oldest first.

        The window starts at local midnight rather than `days * 24` hours ago, so
        it covers whole days as the user experienced them. Callers holding the
        user record already can pass `user_timezone` to save a lookup.
        """
        tz = self._timezone_for(telegram_id, user_timezone)
        today_local = time_utils.now().astimezone(tz).date()
        first_day = today_local - timedelta(days=days - 1)
        since = datetime.combine(first_day, time.min, tzinfo=tz).astimezone(time_utils.UTC)
        return self._entries.find_since(telegram_id, since)

    def toggle_session_flag(self, telegram_id: int) -> dict | None:
        """Flag the latest entry to raise in a therapy session, or unflag it if it already is.

        Returns the entry as it now stands, or None if the user has no entries.
        Only the latest entry can be flagged: the moment someone thinks "I want
        to talk about this" is right after writing it, and anything more needs
        a way to pick an entry that v0 does not have.
        """
        entry = self._entries.find_latest(telegram_id)
        if entry is None:
            return None
        flagged = not entry.get('flagged_for_session', False)
        self._entries.set_flagged(entry['_id'], flagged)
        entry['flagged_for_session'] = flagged
        return entry

    def get_stats(self, telegram_id: int) -> dict:
        return {
            'streak': self._streaks.get(telegram_id),
            'total': self._entries.count(telegram_id),
            'avg_mood': self._entries.average_mood(telegram_id),
        }

    def _update_streak(self, telegram_id: int, now: datetime = None) -> None:
        now = now or time_utils.now()
        tz = self._timezone_for(telegram_id)
        today = now.astimezone(tz).date()

        doc = self._streaks.get_full(telegram_id)
        if doc is None:
            self._streaks.update(telegram_id, 1, now)
            return

        last = time_utils.to_local(doc['last_check_in'], tz).date()
        if last == today:
            return  # already checked in today, in the user's own day

        new_streak = doc['streak'] + 1 if last == today - timedelta(days=1) else 1
        self._streaks.update(telegram_id, new_streak, now)

    def _timezone_for(self, telegram_id: int, name: str = None) -> tzinfo:
        if name is None:
            user = self._users.find(telegram_id) or {}
            name = user.get('timezone')
        return time_utils.resolve_timezone(name, telegram_id)
