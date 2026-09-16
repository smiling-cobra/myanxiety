"""Per-user, per-local-day counters for metered work.

One document per user per day, incremented atomically. The counter is the
enforcement point for the LLM spend ceiling, so the increment and the read have
to be a single operation — two processes, or two overlapping check-ins in the
same process, must not both read the same pre-increment value and both decide
they are under budget.
"""
from __future__ import annotations

from datetime import datetime, timezone

from pymongo import ReturnDocument

from db.db import usage_collection

# Counters describe a single day and are worthless a fortnight later, but they
# are kept long enough to see a week-over-week trend in per-user spend.
USAGE_RETENTION_DAYS = 60


class UsageRepository:
    def __init__(self):
        self._indexed = False

    def increment(self, telegram_id: int, day: str, field: str, amount: int) -> int:
        """Add `amount` to one counter and return its value *after* the write.

        `created_at` is stamped once, when the document is first inserted, and is
        only ever read by the TTL index — retention counts from when a row was
        written, not from the local day it happens to be keyed to.
        """
        self._ensure_indexes()
        doc = usage_collection().find_one_and_update(
            {'telegram_id': telegram_id, 'day': day},
            {'$inc': {field: amount}, '$setOnInsert': {'created_at': datetime.now(timezone.utc)}},
            upsert=True,
            return_document=ReturnDocument.AFTER,
        )
        return doc.get(field, 0)

    def get(self, telegram_id: int, day: str) -> dict | None:
        return usage_collection().find_one({'telegram_id': telegram_id, 'day': day}, {'_id': 0})

    def delete_for_user(self, telegram_id: int) -> int:
        return usage_collection().delete_many({'telegram_id': telegram_id}).deleted_count

    def _ensure_indexes(self) -> None:
        if self._indexed:
            return
        collection = usage_collection()
        collection.create_index([('telegram_id', 1), ('day', 1)], unique=True)
        collection.create_index('created_at', expireAfterSeconds=USAGE_RETENTION_DAYS * 24 * 60 * 60)
        self._indexed = True
