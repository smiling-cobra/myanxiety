from __future__ import annotations

from db.db import entries_collection


class EntryRepository:
    def save(self, entry: dict) -> None:
        entries_collection().insert_one(entry)

    def find_recent(self, telegram_id: int, limit: int = 7) -> list:
        return list(
            entries_collection()
            .find({'telegram_id': telegram_id}, {'_id': 0})
            .sort('created_at', -1)
            .limit(limit)
        )

    def find_latest(self, telegram_id: int) -> dict | None:
        """The newest entry, with its `_id` — the one field the other reads project away."""
        return entries_collection().find_one({'telegram_id': telegram_id}, sort=[('created_at', -1)])

    def set_flagged(self, entry_id, flagged: bool) -> None:
        entries_collection().update_one({'_id': entry_id}, {'$set': {'flagged_for_session': flagged}})

    def count(self, telegram_id: int) -> int:
        return entries_collection().count_documents({'telegram_id': telegram_id})

    def find_since(self, telegram_id: int, since) -> list:
        return list(
            entries_collection()
            .find({'telegram_id': telegram_id, 'created_at': {'$gte': since}}, {'_id': 0})
            .sort('created_at', 1)
        )

    def delete_for_user(self, telegram_id: int) -> int:
        return entries_collection().delete_many({'telegram_id': telegram_id}).deleted_count

    def average_mood(self, telegram_id: int) -> float:
        pipeline = [
            {'$match': {'telegram_id': telegram_id}},
            {'$group': {'_id': None, 'avg': {'$avg': '$mood_score'}}}
        ]
        result = list(entries_collection().aggregate(pipeline))
        avg = result[0]['avg'] if result else None
        return round(avg, 1) if avg is not None else 0.0
