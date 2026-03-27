from __future__ import annotations

from datetime import datetime

from db.db import streaks_collection


class StreakRepository:
    def get(self, telegram_id: int) -> int:
        doc = streaks_collection().find_one({'telegram_id': telegram_id})
        return doc['streak'] if doc else 0

    def get_full(self, telegram_id: int) -> dict | None:
        return streaks_collection().find_one({'telegram_id': telegram_id}, {'_id': 0})

    def update(self, telegram_id: int, streak: int, last_check_in: datetime) -> None:
        streaks_collection().update_one(
            {'telegram_id': telegram_id},
            {'$set': {'streak': streak, 'last_check_in': last_check_in}},
            upsert=True
        )
