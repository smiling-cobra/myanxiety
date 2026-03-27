from datetime import date, datetime, timedelta

from repositories.entry_repo import EntryRepository
from repositories.streak_repo import StreakRepository


class JournalService:
    def __init__(self):
        self._entries = EntryRepository()
        self._streaks = StreakRepository()

    def save_entry(self, telegram_id: int, mood_score: int, text: str, tags: list = None) -> None:
        entry = {
            'telegram_id': telegram_id,
            'mood_score': mood_score,
            'text': text,
            'tags': tags or [],
            'created_at': datetime.utcnow(),
        }
        self._entries.save(entry)
        self._update_streak(telegram_id)

    def get_recent_entries(self, telegram_id: int, limit: int = 7) -> list:
        return self._entries.find_recent(telegram_id, limit)

    def get_stats(self, telegram_id: int) -> dict:
        return {
            'streak': self._streaks.get(telegram_id),
            'total': self._entries.count(telegram_id),
            'avg_mood': self._entries.average_mood(telegram_id),
        }

    def _update_streak(self, telegram_id: int) -> None:
        today = date.today()
        doc = self._streaks.get_full(telegram_id)
        if doc is None:
            self._streaks.update(telegram_id, 1, datetime.utcnow())
            return
        last = doc['last_check_in'].date()
        if last == today:
            return  # already checked in today
        new_streak = doc['streak'] + 1 if last == today - timedelta(days=1) else 1
        self._streaks.update(telegram_id, new_streak, datetime.utcnow())
