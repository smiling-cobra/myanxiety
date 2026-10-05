"""Deleting a user, completely.

`/delete` is easy to half-implement: the obvious collections are `users`,
`entries` and `streaks`, and every other place a user's data lives is one that
a partial implementation quietly leaves behind. This module is the single
enumeration of those places, and the order they are removed in.

**The list is checked, not remembered.** `tests/test_account_service.py`
compares `AccountService.collections` against every collection accessor in `db/db.py`, so
adding a collection without deciding how it is deleted fails CI. It also seeds
every collection through the real write paths and then scans the whole database
for the user's id afterwards.

**Order.** `users` goes first: it is what the scheduler scans, so removing it
stops reminders before anything else is touched, and a user with no record who
messages the bot is simply a new user. Entries — the most sensitive data —
follow immediately. Framework state goes last.

**Partial failure.** Every step is attempted even if an earlier one raises, so
an outage mid-way removes as much as it can, and then `DeletionIncomplete` is
raised naming what is left. Every step is idempotent, so the user's retry
finishes the job.

What this cannot reach is said to the user in `DELETE_CONFIRM_PROMPT`: the
Telegram chat itself, and text already processed by Anthropic.

A live Plus subscription is not data but a standing charge, and deleting the
ledger row that names it would leave Telegram billing an account that no longer
exists. The handler cancels it through the Bot API before this runs.
`payments` is deleted with everything else; Telegram's own Star transaction
record remains the financial record.
"""
from __future__ import annotations

import logging

from repositories.conversation_repo import ConversationRepository
from repositories.entry_repo import EntryRepository
from repositories.event_repo import EventRepository
from repositories.notification_repo import NotificationRepository
from repositories.payment_repo import PaymentRepository
from repositories.streak_repo import StreakRepository
from repositories.usage_repo import UsageRepository
from repositories.user_repo import UserRepository

logger = logging.getLogger(__name__)


class DeletionIncomplete(Exception):
    def __init__(self, failed: list[str]):
        super().__init__(f'Could not delete from: {", ".join(failed)}')
        self.failed = failed


class AccountService:
    def __init__(self):
        users, entries, streaks = UserRepository(), EntryRepository(), StreakRepository()
        conversations = ConversationRepository()
        # (collection name, deleter) — in the order they are removed.
        self._fan_out = (
            ('users', users.delete_for_user),
            ('entries', entries.delete_for_user),
            ('streaks', streaks.delete_for_user),
            ('notifications', NotificationRepository().delete_for_user),
            ('usage', UsageRepository().delete_for_user),
            ('payments', PaymentRepository().delete_for_user),
            ('events', EventRepository().delete_for_user),
            ('ptb_user_data', conversations.delete_user_data_for_user),
            ('ptb_conversations', conversations.delete_conversations_for_user),
        )

    @property
    def collections(self) -> tuple[str, ...]:
        """Every collection the fan-out reaches, in deletion order."""
        return tuple(name for name, _ in self._fan_out)

    def delete_everything(self, telegram_id: int) -> dict[str, int]:
        """Remove every record linked to `telegram_id`. Returns rows removed per collection.

        Raises `DeletionIncomplete` if any step failed — after attempting all of them.
        """
        removed: dict[str, int] = {}
        failed: list[str] = []
        for name, delete in self._fan_out:
            try:
                removed[name] = delete(telegram_id)
            except Exception:
                logger.exception('Deleting %s for user %s failed', name, telegram_id)
                failed.append(name)
        if failed:
            raise DeletionIncomplete(failed)
        logger.info('Deleted all data for user %s: %s', telegram_id, removed)
        return removed
