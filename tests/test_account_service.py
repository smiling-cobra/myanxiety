"""Tests for the /delete fan-out.

The two tests that matter most here do not trust the list in
`services/account_service.py`, because a hand-maintained list is exactly how a
delete flow ends up half-implemented:

* every collection accessor in `db/db.py` must be in the fan-out, so a new
  collection cannot ship without a decision about how it is deleted; and
* after seeding every store through the code paths that really write to it,
  the whole database is scanned for the user's id — not just the collections
  the fan-out already knows about.
"""
from __future__ import annotations

import inspect
from datetime import datetime, timezone
from unittest.mock import patch

import pytest

import db.db as db_module
from bot.persistence import MongoPersistence
from db.db import notifications_collection
from services.account_service import AccountService, DeletionIncomplete
from services.analytics_service import AnalyticsService
from services.journal_service import JournalService
from services.usage_service import UsageService
from services.user_service import UserService

USER = 707070
OTHER = 808080


@pytest.fixture
def svc():
    return AccountService()


async def _seed(telegram_id: int) -> None:
    """Write to every PII-bearing store the way the running bot does."""
    UserService().create_or_update(
        telegram_id, name='Sam', timezone='Europe/London', reminder_time='09:00', onboarded=True,
        acquisition_source='reddit', in_therapy='yes', last_reminder_sent='2026-09-30',
    )
    journal = JournalService()
    journal.save_entry(telegram_id, 3, 'something private', ['work'])
    journal.save_entry(telegram_id, 6, 'something else private', ['sleep'])
    UsageService().consume_llm(telegram_id, 2)
    AnalyticsService().track('check_in_completed', telegram_id, mood_score=3)
    notifications_collection().insert_one({'telegram_id': telegram_id, 'kind': 'legacy'})

    persistence = MongoPersistence()
    await persistence.update_user_data(telegram_id, {'name': 'Sam', 'mood_score': 3})
    await persistence.update_conversation('journal', (telegram_id, telegram_id), 3)


def _mentions(value, telegram_id: int) -> bool:
    if isinstance(value, dict):
        return any(_mentions(v, telegram_id) for v in value.values())
    if isinstance(value, (list, tuple)):
        return any(_mentions(v, telegram_id) for v in value)
    return value == telegram_id


def _rows_mentioning(db, telegram_id: int) -> dict[str, int]:
    """Every row, in every collection, with the id anywhere in it (including `_id`)."""
    found = {}
    for name in db.list_collection_names():
        count = sum(1 for doc in db[name].find({}) if _mentions(doc, telegram_id))
        if count:
            found[name] = count
    return found


class TestTheFanOutIsComplete:
    def test_every_collection_accessor_in_db_is_deleted_from(self, svc):
        accessors = [
            fn for name, fn in inspect.getmembers(db_module, inspect.isfunction)
            if name.endswith('_collection') and name != 'get_collection'
        ]
        assert accessors, 'found no collection accessors — has db/db.py been restructured?'
        collections = {fn().name for fn in accessors}
        assert collections - set(svc.collections) == set()

    async def test_nothing_linked_to_the_user_survives(self, svc, mock_db):
        await _seed(USER)
        assert set(_rows_mentioning(mock_db, USER)) == set(svc.collections), 'seed should touch every store'

        svc.delete_everything(USER)

        assert _rows_mentioning(mock_db, USER) == {}

    async def test_other_users_are_untouched(self, svc, mock_db):
        await _seed(USER)
        await _seed(OTHER)
        before = _rows_mentioning(mock_db, OTHER)

        svc.delete_everything(USER)

        assert _rows_mentioning(mock_db, OTHER) == before

    async def test_counts_are_reported_per_collection(self, svc):
        await _seed(USER)
        removed = svc.delete_everything(USER)
        assert removed['entries'] == 2
        assert removed['users'] == 1
        assert list(removed) == list(svc.collections)

    def test_deleting_a_user_with_no_data_is_harmless(self, svc):
        assert set(svc.delete_everything(USER).values()) == {0}

    async def test_deleting_twice_is_safe(self, svc, mock_db):
        await _seed(USER)
        svc.delete_everything(USER)
        svc.delete_everything(USER)
        assert _rows_mentioning(mock_db, USER) == {}


class TestPartialFailure:
    async def test_every_step_is_attempted_before_raising(self, svc, mock_db):
        await _seed(USER)
        with patch('repositories.entry_repo.entries_collection', side_effect=Exception('Mongo blip')):
            with pytest.raises(DeletionIncomplete) as raised:
                svc.delete_everything(USER)

        assert raised.value.failed == ['entries']
        # Everything else went, so what is left is exactly what failed.
        assert set(_rows_mentioning(mock_db, USER)) == {'entries'}

    async def test_a_retry_finishes_the_job(self, svc, mock_db):
        await _seed(USER)
        with patch('repositories.entry_repo.entries_collection', side_effect=Exception('Mongo blip')):
            with pytest.raises(DeletionIncomplete):
                svc.delete_everything(USER)

        svc.delete_everything(USER)
        assert _rows_mentioning(mock_db, USER) == {}


class TestNothingRecreatesADeletedUser:
    async def test_a_scheduler_watermark_written_after_deletion_creates_no_user(self, svc, mock_db):
        """A reminder job already running when the user confirmed must not
        upsert a skeleton record back into existence."""
        await _seed(USER)
        svc.delete_everything(USER)

        UserService().update(USER, last_reminder_sent=datetime.now(timezone.utc).date().isoformat())

        assert _rows_mentioning(mock_db, USER) == {}
