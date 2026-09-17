"""Tests for the v0 export — the file a user takes to a therapy session."""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pytest

from repositories.entry_repo import EntryRepository
from repositories.user_repo import UserRepository
from services.export import EXPORT_DAYS, ExportService
from services.export.markdown import render_export

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

    def test_works_without_a_user_record(self, svc):
        _entry('orphaned but still theirs')
        export, text = _build(svc)
        assert 'orphaned but still theirs' in text
        assert text.startswith('# Journal\n')


def _render(entries, tz=UTC, name='Sam') -> str:
    return render_export(name, entries, tz, date(2026, 9, 30))


def _e(text='x', mood=5, when=NOW, tags=None, flagged=None) -> dict:
    entry = {'text': text, 'mood_score': mood, 'created_at': when, 'tags': tags or []}
    if flagged is not None:
        entry['flagged_for_session'] = flagged
    return entry


class TestRender:
    def test_summary_counts_entries_days_and_mood(self):
        text = _render([
            _e(mood=2, when=NOW - timedelta(days=2)),
            _e(mood=6, when=NOW - timedelta(days=1)),
            _e(mood=7, when=NOW),
            _e(mood=9, when=NOW + timedelta(minutes=5)),
        ])
        assert '**Entries:** 4 on 3 different days' in text
        assert 'average 6.0/10, lowest 2, highest 9' in text

    def test_themes_are_normalised_and_counted_per_entry(self):
        text = _render([
            _e(tags=['job', 'insomnia']),
            _e(tags=['Work', 'work stress']),
            _e(tags=['sleep']),
        ])
        assert '**Most common themes:** work (2), sleep (2)' in text

    def test_legacy_fallback_prose_is_not_a_theme(self):
        text = _render([_e(tags=["I'm having trouble responding right now. Please try again later."])])
        assert 'none recorded' in text
        assert 'trouble' not in text

    def test_entries_read_oldest_first(self):
        text = _render([_e('first', when=NOW - timedelta(days=1)), _e('second')])
        assert text.index('first') < text.index('second')

    def test_times_are_local(self):
        text = _render([_e(when=datetime(2026, 9, 29, 23, 30, tzinfo=UTC))], tz=ZoneInfo('Europe/Berlin'))
        assert 'Wed 30 Sep 2026, 01:30' in text

    def test_multi_line_entries_stay_quoted(self):
        text = _render([_e('line one\n\nline two')])
        assert '> line one\n>\n> line two' in text

    def test_user_text_cannot_become_markdown_structure(self):
        text = _render([_e('# not a heading\n- not a list')])
        assert '> \\# not a heading' in text
        assert '> \\- not a list' in text

    def test_says_what_it_is_not(self):
        assert 'not a clinical record' in _render([_e()])


class TestSessionFlags:
    def test_flagged_entries_are_listed_before_everything_else(self):
        text = _render([
            _e('an ordinary day', when=NOW - timedelta(days=1)),
            _e('the thing I want to talk about', mood=3, flagged=True),
        ])
        assert '## To raise in session' in text
        assert text.index('## To raise in session') < text.index('## At a glance')
        section = text.split('## To raise in session')[1].split('## At a glance')[0]
        assert 'the thing I want to talk about' in section
        assert 'an ordinary day' not in section

    def test_no_flags_no_section(self):
        assert 'To raise in session' not in _render([_e(), _e(flagged=False)])

    def test_the_entry_itself_is_marked(self):
        text = _render([_e('flag me', flagged=True)])
        entries = text.split('## Entries')[1]
        assert 'Flagged to raise in session' in entries

    def test_long_entries_are_previewed_on_one_line(self):
        long_text = 'word ' * 60 + '\nsecond line'
        section = _render([_e(long_text, flagged=True)]).split('## To raise in session')[1].split('##')[0]
        preview = [line for line in section.splitlines() if line.startswith('- ')]
        assert len(preview) == 1
        assert preview[0].endswith('…')

    def test_build_counts_flags(self, svc):
        _user()
        _entry('one')
        _entry('two', when=NOW + timedelta(minutes=1))
        with patch('services.time_utils.now', return_value=NOW + timedelta(minutes=2)):
            from services.journal_service import JournalService
            JournalService().toggle_session_flag(USER)
            export = svc.build(USER)
        assert export.flagged_count == 1
