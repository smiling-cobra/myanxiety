"""Tests for building the v0 export — what is loaded, and how the file is packaged.

What the file says is tested in test_export_digest.py, and how it is laid out in
test_export_markdown.py."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

from repositories.entry_repo import EntryRepository
from repositories.user_repo import UserRepository
from services.export import EXPORT_DAYS, ExportService
from services.journal_service import JournalService

USER = 515151
OTHER = 616161
UTC = timezone.utc
NOW = datetime(2026, 9, 30, 12, 0, tzinfo=UTC)


@pytest.fixture
def svc():
    return ExportService()


def _user(**fields) -> None:
    UserRepository().save({'telegram_id': USER, 'name': 'Sam', 'timezone': 'UTC', 'onboarded': True, **fields})


def _entry(text: str, mood: int = 5, when: datetime = NOW, tags=None, user: int = USER) -> None:
    EntryRepository().save({
        'telegram_id': user, 'mood_score': mood, 'text': text, 'tags': tags or [], 'created_at': when,
    })


def _build(svc) -> tuple:
    with patch('services.time_utils.now', return_value=NOW):
        export = svc.build(USER)
    return export, (export.content.decode('utf-8') if export else None)


class TestBuild:
    def test_nothing_to_export_is_none(self, svc):
        _user()
        export, _ = _build(svc)
        assert export is None

    def test_entries_are_included_in_full(self, svc):
        _user()
        long_text = 'A long entry. ' * 100
        _entry(long_text.strip())
        _, text = _build(svc)
        assert long_text.strip() in text

    def test_window_is_the_last_export_days_local_days(self, svc):
        _user()
        _entry('inside', when=NOW - timedelta(days=EXPORT_DAYS - 1))
        _entry('outside', when=NOW - timedelta(days=EXPORT_DAYS + 1))
        export, text = _build(svc)
        assert export.entry_count == 1
        assert 'inside' in text
        assert 'outside' not in text

    def test_other_users_entries_never_appear(self, svc):
        _user()
        _entry('mine')
        _entry('someone else', user=OTHER)
        _, text = _build(svc)
        assert 'someone else' not in text

    def test_filename_carries_the_local_date(self, svc):
        # Kiritimati is UTC+14: noon UTC on the 30th is already 1 October there.
        _user(timezone='Pacific/Kiritimati')
        _entry('x')
        export, _ = _build(svc)
        assert export.filename == 'journal-2026-10-01.md'

    def test_no_model_is_involved(self, svc):
        """Deterministic by design: nothing in the file was written by anyone but the user."""
        _user()
        _entry('x')
        with patch('services.llm_service.LlmService') as llm:
            _build(svc)
        llm.assert_not_called()

    def test_name_comes_from_the_user_record(self, svc):
        _user(name='Alex')
        _entry('x')
        _, text = _build(svc)
        assert text.startswith('# Journal — Alex\n')

    def test_works_without_a_user_record(self, svc):
        _entry('orphaned but still theirs')
        export, text = _build(svc)
        assert 'orphaned but still theirs' in text
        assert text.startswith('# Journal\n')

    def test_counts_flags(self, svc):
        _user()
        _entry('one')
        _entry('two', when=NOW + timedelta(minutes=1))
        with patch('services.time_utils.now', return_value=NOW + timedelta(minutes=2)):
            JournalService().toggle_session_flag(USER)
            export = svc.build(USER)
        assert (export.entry_count, export.flagged_count) == (2, 1)
        assert '## To raise in session' in export.content.decode('utf-8')
