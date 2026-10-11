"""What users send through /feedback.

One row per message: `{telegram_id, text, created_at, is_plus}`. This is
user-written text stored outside `entries`, so it is in the /delete fan-out.
"""
from __future__ import annotations

from db.db import feedback_collection


class FeedbackRepository:
    def add(self, feedback: dict) -> None:
        feedback_collection().insert_one(dict(feedback))

    def count_since(self, telegram_id: int, since) -> int:
        return feedback_collection().count_documents({'telegram_id': telegram_id, 'created_at': {'$gte': since}})

    def delete_for_user(self, telegram_id: int) -> int:
        return feedback_collection().delete_many({'telegram_id': telegram_id}).deleted_count
