"""Tests for boot-time index creation."""
from unittest.mock import patch

import pytest
from pymongo.errors import OperationFailure, ServerSelectionTimeoutError

from db.indexes import INDEXES, ensure_indexes


def _names(db, collection: str) -> set:
    return set(db[collection].index_information())


class TestEnsureIndexes:
    def test_every_index_is_created(self, mock_db):
        assert ensure_indexes(mock_db) == []
        for collection, _, options in INDEXES:
            assert options['name'] in _names(mock_db, collection)

    def test_the_user_scoped_lookups_are_covered(self, mock_db):
        ensure_indexes(mock_db)
        entries = mock_db['entries'].index_information()['telegram_id_created_at']['key']
        assert [field for field, _ in entries] == ['telegram_id', 'created_at']
        assert mock_db['users'].index_information()['telegram_id_unique']['unique']
        assert mock_db['streaks'].index_information()['telegram_id_unique']['unique']

    def test_running_twice_is_harmless(self, mock_db):
        """It runs on every boot."""
        ensure_indexes(mock_db)
        assert ensure_indexes(mock_db) == []

    def test_a_second_account_for_the_same_user_is_refused(self, mock_db):
        from pymongo.errors import DuplicateKeyError
        ensure_indexes(mock_db)
        mock_db['users'].insert_one({'telegram_id': 1})
        with pytest.raises(DuplicateKeyError):
            mock_db['users'].insert_one({'telegram_id': 1})

    def test_existing_duplicates_skip_that_index_and_not_the_boot(self, mock_db, caplog):
        mock_db['users'].insert_many([{'telegram_id': 1}, {'telegram_id': 1}])
        assert ensure_indexes(mock_db) == ['users.telegram_id_unique']
        assert 'users.telegram_id_unique' in caplog.text
        assert 'telegram_id_created_at' in _names(mock_db, 'entries')

    def test_one_failure_does_not_stop_the_rest(self, mock_db):
        collection_type = type(mock_db['users'])
        create_index = collection_type.create_index

        def refuse_users(collection, keys, **options):
            if collection.name == 'users':
                raise OperationFailure('boom')
            return create_index(collection, keys, **options)

        with patch.object(collection_type, 'create_index', refuse_users):
            failed = ensure_indexes(mock_db)
        assert failed == ['users.telegram_id_unique', 'users.onboarded']
        assert 'telegram_id_unique' in _names(mock_db, 'streaks')

    def test_an_unreachable_database_fails_the_boot(self, mock_db):
        with patch.object(type(mock_db), 'command', side_effect=ServerSelectionTimeoutError('no servers')):
            with pytest.raises(ServerSelectionTimeoutError):
                ensure_indexes(mock_db)
