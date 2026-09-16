"""Append-only storage for analytics events.

Indexes are created on first write rather than at import, so constructing the
repository never opens a connection — the services are built at import time and
a DB round trip there would move a Mongo outage from the first check-in to boot.
"""
from __future__ import annotations

from datetime import datetime

from db.db import events_collection

# Behavioural events answer "is the product working" over weeks, not years, and
# every one of them is user-linked. Mongo drops them on this schedule without
# anyone having to remember to, which keeps the retention promise a property of
# the database rather than of a future cleanup script.
EVENT_RETENTION_DAYS = 180


class EventRepository:
    def __init__(self):
        self._indexed = False

    def save(self, event: dict) -> None:
        self._ensure_indexes()
        events_collection().insert_one(event)

    def find_recent(self, telegram_id: int, limit: int = 50) -> list:
        return list(
            events_collection()
            .find({'telegram_id': telegram_id}, {'_id': 0})
            .sort('created_at', -1)
            .limit(limit)
        )

    def count_since(self, event: str, since: datetime) -> int:
        return events_collection().count_documents({'event': event, 'created_at': {'$gte': since}})

    def delete_for_user(self, telegram_id: int) -> int:
        """Every event belonging to one user — the /delete fan-out reaches this."""
        return events_collection().delete_many({'telegram_id': telegram_id}).deleted_count

    def _ensure_indexes(self) -> None:
        if self._indexed:
            return
        collection = events_collection()
        collection.create_index('created_at', expireAfterSeconds=EVENT_RETENTION_DAYS * 24 * 60 * 60)
        collection.create_index([('telegram_id', 1), ('created_at', -1)])
        collection.create_index([('event', 1), ('created_at', -1)])
        self._indexed = True
