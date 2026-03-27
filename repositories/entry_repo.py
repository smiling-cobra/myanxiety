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

    def count(self, telegram_id: int) -> int:
        return entries_collection().count_documents({'telegram_id': telegram_id})

    def average_mood(self, telegram_id: int) -> float:
        pipeline = [
            {'$match': {'telegram_id': telegram_id}},
            {'$group': {'_id': None, 'avg': {'$avg': '$mood_score'}}}
        ]
        result = list(entries_collection().aggregate(pipeline))
        avg = result[0]['avg'] if result else None
        return round(avg, 1) if avg is not None else 0.0
