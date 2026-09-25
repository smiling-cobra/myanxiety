"""The ledger of Telegram Stars payments.

One row per successful payment, keyed by Telegram's charge id. The unique index
is what makes a redelivered `successful_payment` update harmless, so it is
created here on first write, like the usage counter's, rather than left to boot.

Only ids, amounts and dates are stored. Telegram's own Star transaction record
(`getStarTransactions`) stays the financial record of truth; this ledger exists
so the bot can find the charge to cancel or refund.
"""
from __future__ import annotations

from pymongo import DESCENDING
from pymongo.errors import DuplicateKeyError

from db.db import payments_collection


class PaymentRepository:
    def __init__(self):
        self._indexed = False

    def record(self, payment: dict) -> bool:
        """Insert one payment. False if its charge id was already recorded."""
        self._ensure_indexes()
        try:
            payments_collection().insert_one(dict(payment))
        except DuplicateKeyError:
            return False
        return True

    def find(self, charge_id: str) -> dict | None:
        return payments_collection().find_one({'telegram_payment_charge_id': charge_id}, {'_id': 0})

    def latest_recurring(self, telegram_id: int) -> dict | None:
        """The newest unrefunded subscription payment — the charge a cancellation names."""
        return payments_collection().find_one(
            {'telegram_id': telegram_id, 'is_recurring': True, 'refunded_at': None},
            {'_id': 0},
            sort=[('created_at', DESCENDING)],
        )

    def mark_refunded(self, charge_id: str, when) -> None:
        payments_collection().update_one(
            {'telegram_payment_charge_id': charge_id}, {'$set': {'refunded_at': when}}
        )

    def delete_for_user(self, telegram_id: int) -> int:
        return payments_collection().delete_many({'telegram_id': telegram_id}).deleted_count

    def _ensure_indexes(self) -> None:
        if self._indexed:
            return
        collection = payments_collection()
        collection.create_index('telegram_payment_charge_id', unique=True)
        collection.create_index([('telegram_id', 1), ('created_at', DESCENDING)])
        self._indexed = True
