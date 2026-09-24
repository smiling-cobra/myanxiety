"""Tests for /settings: changing the reminder time, pausing, resuming early.

The handlers run against the real `UserService` on the mongomock database from
conftest, so a test can read back what was actually stored. The clock is the
`time_utils.now` seam; analytics is patched so its calls can be inspected.
"""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
from unittest.mock import patch

import pytest

from bot.handlers.journal import (
    MAIN_MENU,
    SETTINGS_MENU,
    SETTINGS_PAUSE_LENGTH,
    SETTINGS_TIME,
    handle_main_menu,
    handle_pause_length,
    handle_settings_choice,
    handle_settings_time,
    recover_state,
    show_settings,
)
from bot.handlers.journal.settings import pause_end
from bot.keyboards import (
    BACK,
    CHANGE_REMINDER_TIME,
    PAUSE_REMINDERS,
    RESUME_REMINDERS,
    SETTINGS,
    get_main_menu_keyboard,
)
from repositories.user_repo import UserRepository
from services.time_utils import parse_reminder_time
from tests.conftest import make_context as _context, make_update as _update

USER_ID = 12345

# Thursday 24 September 2026, 10:00 UTC.
_NOW = datetime(2026, 9, 24, 10, 0, tzinfo=timezone.utc)


def _save_user(**fields) -> None:
    UserRepository().save({
        'telegram_id': USER_ID,
        'name': 'Sam',
        'timezone': 'Europe/London',
        'reminder_time': '09:00',
        'onboarded': True,
        **fields,
    })


def _stored() -> dict:
    return UserRepository().find(USER_ID)


@contextmanager
def _at(now: datetime = _NOW):
    with patch('services.time_utils.now', return_value=now), \
         patch('bot.handlers.journal.deps.analytics_svc') as analytics:
        yield analytics


def _tracked(analytics) -> dict:
    return {c.args[0]: c.kwargs for c in analytics.track.call_args_list}


def _reply(update) -> str:
    return update.message.reply_text.call_args.args[0]


def _buttons(update) -> list[str]:
    markup = update.message.reply_text.call_args.kwargs['reply_markup']
    return [button.text for row in markup.keyboard for button in row]


# ---------------------------------------------------------------------------
# Shared reminder-time parser
# ---------------------------------------------------------------------------

class TestParseReminderTime:
    @pytest.mark.parametrize('text, expected', [
        ('09:00', '09:00'),
        (' 21:30 ', '21:30'),
        ('00:00', '00:00'),
        ('23:59', '23:59'),
    ])
    def test_valid(self, text, expected):
        assert parse_reminder_time(text) == expected

    @pytest.mark.parametrize('text', ['0900', '9:00', 'nine', '24:00', '09:60', '', None])
    def test_invalid(self, text):
        assert parse_reminder_time(text) is None


# ---------------------------------------------------------------------------
# Opening settings
# ---------------------------------------------------------------------------

class TestShowSettings:
    async def test_shows_the_current_time_and_status(self):
        _save_user(timezone='America/New_York')
        update = _update('/settings')
        with _at():
            state = await show_settings(update, _context())
        assert state == SETTINGS_MENU
        text = _reply(update)
        assert '09:00' in text
        assert 'America/New\\_York' in text  # escaped for Markdown
        assert 'Reminders are on.' in text
        assert PAUSE_REMINDERS in _buttons(update)
        assert RESUME_REMINDERS not in _buttons(update)

    async def test_a_running_pause_is_shown_with_its_end_date(self):
        _save_user(reminders_paused_until='2026-09-27')
        update = _update('/settings')
        with _at():
            await show_settings(update, _context())
        assert 'paused until *Sunday 27 September*' in _reply(update)
        assert RESUME_REMINDERS in _buttons(update)
        assert PAUSE_REMINDERS not in _buttons(update)

    async def test_a_pause_that_has_run_out_reads_as_on(self):
        _save_user(reminders_paused_until='2026-09-24')
        update = _update('/settings')
        with _at():
            await show_settings(update, _context())
        assert 'Reminders are on.' in _reply(update)

    async def test_viewing_is_recorded(self):
        _save_user()
        with _at() as analytics:
            await show_settings(_update('/settings'), _context())
        assert 'settings_viewed' in _tracked(analytics)

    async def test_not_available_before_the_account_exists(self):
        """Before the reminder-time step there is nothing to configure, and the
        step in progress must not be lost: None leaves the conversation where it was."""
        UserRepository().save({'telegram_id': USER_ID, 'acquisition_source': 'direct'})
        update = _update('/settings')
        with _at():
            state = await show_settings(update, _context())
        assert state is None
        assert update.message.reply_text.called

    async def test_opens_at_the_optional_cohort_question(self):
        """`onboarded` is written with the reminder time, before the cohort
        question, so the account is complete there. Settings open as any other
        command would, and the optional question is left unanswered."""
        _save_user()  # onboarded, no `in_therapy` yet
        with _at():
            state = await show_settings(_update('/settings'), _context())
        assert state == SETTINGS_MENU

    async def test_the_main_menu_button_opens_settings(self):
        _save_user()
        with _at():
            state = await handle_main_menu(_update(SETTINGS), _context({'name': 'Sam'}))
        assert state == SETTINGS_MENU

    async def test_a_stale_settings_button_works_after_recovery(self):
        _save_user()
        with _at():
            state = await recover_state(_update(SETTINGS), _context())
        assert state == SETTINGS_MENU

    def test_the_main_menu_has_a_settings_button(self):
        buttons = [b.text for row in get_main_menu_keyboard().keyboard for b in row]
        assert SETTINGS in buttons


# ---------------------------------------------------------------------------
# Changing the reminder time
# ---------------------------------------------------------------------------

class TestChangeReminderTime:
    async def test_asks_for_the_new_time(self):
        _save_user()
        update = _update(CHANGE_REMINDER_TIME)
        with _at():
            state = await handle_settings_choice(update, _context())
        assert state == SETTINGS_TIME
        assert '09:00' in _reply(update)

    async def test_a_valid_time_is_saved(self):
        _save_user()
        update = _update('21:30')
        with _at():
            state = await handle_settings_time(update, _context())
        assert state == MAIN_MENU
        assert _stored()['reminder_time'] == '21:30'
        assert '21:30' in _reply(update)

    async def test_the_change_touches_nothing_else(self):
        """Watermarks stay as they are: a user already reminded today is not
        reminded again at the new time (see the scheduler tests)."""
        _save_user(last_reminder_sent='2026-09-24', reminders_paused_until='2026-09-27')
        with _at():
            await handle_settings_time(_update('21:30'), _context())
        stored = _stored()
        assert stored['last_reminder_sent'] == '2026-09-24'
        assert stored['reminders_paused_until'] == '2026-09-27'

    @pytest.mark.parametrize('text', ['9pm', '25:00', '09:60', '0900'])
    async def test_an_invalid_time_is_asked_again(self, text):
        _save_user()
        update = _update(text)
        with _at():
            state = await handle_settings_time(update, _context())
        assert state == SETTINGS_TIME
        assert _stored()['reminder_time'] == '09:00'
        assert 'HH:MM' in _reply(update)

    async def test_back_returns_to_settings_unchanged(self):
        _save_user()
        with _at():
            state = await handle_settings_time(_update(BACK), _context())
        assert state == SETTINGS_MENU
        assert _stored()['reminder_time'] == '09:00'

    async def test_while_paused_the_reply_says_when_it_applies(self):
        _save_user(reminders_paused_until='2026-09-27')
        update = _update('08:00')
        with _at():
            await handle_settings_time(update, _context())
        assert 'still paused' in _reply(update)
        assert 'Sunday 27 September' in _reply(update)

    async def test_recorded_with_the_hour_only(self):
        _save_user()
        with _at() as analytics:
            await handle_settings_time(_update('21:30'), _context())
        assert _tracked(analytics)['reminder_time_changed'] == {'hour': 21}

    async def test_a_deleted_account_is_not_recreated(self):
        """A settings keyboard can outlive /delete."""
        with _at():
            await handle_settings_time(_update('21:30'), _context())
        assert _stored() is None


# ---------------------------------------------------------------------------
# Pausing
# ---------------------------------------------------------------------------

class TestPause:
    async def test_asks_how_long(self):
        _save_user()
        update = _update(PAUSE_REMINDERS)
        with _at():
            state = await handle_settings_choice(update, _context())
        assert state == SETTINGS_PAUSE_LENGTH
        assert {'3 days', '1 week', '2 weeks'} <= set(_buttons(update))

    @pytest.mark.parametrize('choice, until', [
        ('3 days', '2026-09-27'),
        ('1 week', '2026-10-01'),
        ('2 weeks', '2026-10-08'),
    ])
    async def test_stores_the_date_reminders_resume(self, choice, until):
        _save_user()
        with _at():
            state = await handle_pause_length(_update(choice), _context())
        assert state == MAIN_MENU
        assert _stored()['reminders_paused_until'] == until

    async def test_counts_from_the_users_local_today(self):
        # 23:30 UTC on the 24th is already the 25th in Tokyo.
        _save_user(timezone='Asia/Tokyo')
        with _at(datetime(2026, 9, 24, 23, 30, tzinfo=timezone.utc)):
            await handle_pause_length(_update('3 days'), _context())
        assert _stored()['reminders_paused_until'] == '2026-09-28'

    async def test_leaves_the_reminder_time_alone(self):
        _save_user()
        with _at():
            await handle_pause_length(_update('1 week'), _context())
        assert _stored()['reminder_time'] == '09:00'

    async def test_the_reply_is_a_break_not_a_goodbye(self):
        _save_user()
        update = _update('3 days')
        with _at():
            await handle_pause_length(update, _context())
        text = _reply(update)
        assert 'Sunday 27 September' in text
        assert 'still write' in text
        assert 'streak' not in text.lower()

    async def test_an_unknown_length_is_asked_again(self):
        _save_user()
        with _at():
            state = await handle_pause_length(_update('forever'), _context())
        assert state == SETTINGS_PAUSE_LENGTH
        assert 'reminders_paused_until' not in _stored()

    async def test_back_returns_to_settings_without_pausing(self):
        _save_user()
        with _at():
            state = await handle_pause_length(_update(BACK), _context())
        assert state == SETTINGS_MENU
        assert 'reminders_paused_until' not in _stored()

    async def test_recorded_with_its_length(self):
        _save_user()
        with _at() as analytics:
            await handle_pause_length(_update('1 week'), _context())
        assert _tracked(analytics)['reminders_paused'] == {'days': 7}


# ---------------------------------------------------------------------------
# Resuming early
# ---------------------------------------------------------------------------

class TestResume:
    async def test_clears_the_pause(self):
        _save_user(reminders_paused_until='2026-09-27')
        update = _update(RESUME_REMINDERS)
        with _at() as analytics:
            state = await handle_settings_choice(update, _context())
        assert state == MAIN_MENU
        assert pause_end(_stored()) is None
        assert '09:00' in _reply(update)
        assert 'reminders_resumed' in _tracked(analytics)

    async def test_with_no_pause_running_just_shows_settings(self):
        _save_user(reminders_paused_until='2026-09-20')
        with _at() as analytics:
            state = await handle_settings_choice(_update(RESUME_REMINDERS), _context())
        assert state == SETTINGS_MENU
        assert 'reminders_resumed' not in _tracked(analytics)


class TestSettingsMenu:
    async def test_back_goes_to_the_main_menu(self):
        _save_user()
        update = _update(BACK)
        with _at():
            state = await handle_settings_choice(update, _context())
        assert state == MAIN_MENU
        assert 'Sam' in _reply(update)

    async def test_unknown_text_shows_settings_again(self):
        _save_user()
        with _at():
            state = await handle_settings_choice(_update('hmm'), _context())
        assert state == SETTINGS_MENU

    async def test_a_failed_read_falls_back_to_the_main_menu(self):
        with _at(), patch('bot.handlers.journal.deps.user_svc') as mock_svc:
            mock_svc.get.side_effect = Exception('mongo down')
            state = await handle_settings_choice(_update(PAUSE_REMINDERS), _context())
        assert state == MAIN_MENU
