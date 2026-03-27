"""Tests for handler input validation.

Strategy: call handler functions directly with mocked Update / CallbackContext
and assert the returned conversation-state integer. No Telegram API is hit.
LLM and DB calls are patched wherever a handler reaches them.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from bot.handlers.journal import (
    CHECK_IN_MOOD,
    CHECK_IN_TEXT,
    MAIN_MENU,
    ONBOARDING_TIME,
    ONBOARDING_TIMEZONE,
    handle_mood,
    handle_reminder_time,
    handle_timezone,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _update(text: str, user_id: int = 12345) -> MagicMock:
    u = MagicMock()
    u.message.text = text
    u.effective_user.id = user_id
    return u


def _context(user_data: dict | None = None) -> MagicMock:
    c = MagicMock()
    c.user_data = user_data if user_data is not None else {}
    return c


# ---------------------------------------------------------------------------
# Timezone validation
# ---------------------------------------------------------------------------

class TestHandleTimezone:
    def test_valid_iana_timezone_advances_state(self):
        ctx = _context({'name': 'Alice'})
        result = handle_timezone(_update('Europe/London'), ctx)
        assert result == ONBOARDING_TIME

    def test_valid_timezone_stored_in_user_data(self):
        ctx = _context({'name': 'Alice'})
        handle_timezone(_update('America/New_York'), ctx)
        assert ctx.user_data['timezone'] == 'America/New_York'

    def test_invalid_timezone_stays_on_same_state(self):
        ctx = _context({'name': 'Alice'})
        result = handle_timezone(_update('Mars/Olympus'), ctx)
        assert result == ONBOARDING_TIMEZONE

    def test_plain_city_name_is_rejected(self):
        result = handle_timezone(_update('London'), _context({'name': 'Alice'}))
        assert result == ONBOARDING_TIMEZONE

    def test_utc_is_accepted(self):
        ctx = _context({'name': 'Alice'})
        result = handle_timezone(_update('UTC'), ctx)
        assert result == ONBOARDING_TIME


# ---------------------------------------------------------------------------
# Reminder time validation
# ---------------------------------------------------------------------------

class TestHandleReminderTime:
    def _ctx(self) -> MagicMock:
        return _context({'name': 'Alice', 'timezone': 'Europe/London'})

    def test_valid_time_advances_to_main_menu(self):
        with patch('bot.handlers.journal._user_svc'):
            result = handle_reminder_time(_update('09:00'), self._ctx())
        assert result == MAIN_MENU

    def test_valid_time_saves_user(self):
        with patch('bot.handlers.journal._user_svc') as mock_svc:
            handle_reminder_time(_update('21:30'), self._ctx())
        mock_svc.create_or_update.assert_called_once()

    def test_no_colon_stays(self):
        result = handle_reminder_time(_update('0900'), self._ctx())
        assert result == ONBOARDING_TIME

    def test_letters_stay(self):
        result = handle_reminder_time(_update('nine'), self._ctx())
        assert result == ONBOARDING_TIME

    def test_hour_25_stays(self):
        result = handle_reminder_time(_update('25:00'), self._ctx())
        assert result == ONBOARDING_TIME

    def test_minute_60_stays(self):
        result = handle_reminder_time(_update('09:60'), self._ctx())
        assert result == ONBOARDING_TIME

    def test_boundary_midnight(self):
        with patch('bot.handlers.journal._user_svc'):
            result = handle_reminder_time(_update('00:00'), self._ctx())
        assert result == MAIN_MENU

    def test_boundary_last_minute_of_day(self):
        with patch('bot.handlers.journal._user_svc'):
            result = handle_reminder_time(_update('23:59'), self._ctx())
        assert result == MAIN_MENU


# ---------------------------------------------------------------------------
# Mood score validation
# ---------------------------------------------------------------------------

class TestHandleMood:
    def test_valid_score_advances_state(self):
        ctx = _context({'name': 'Alice'})
        result = handle_mood(_update('7'), ctx)
        assert result == CHECK_IN_TEXT

    def test_score_stored_in_user_data(self):
        ctx = _context({'name': 'Alice'})
        handle_mood(_update('7'), ctx)
        assert ctx.user_data['mood_score'] == 7

    def test_lower_boundary_accepted(self):
        result = handle_mood(_update('1'), _context({'name': 'A'}))
        assert result == CHECK_IN_TEXT

    def test_upper_boundary_accepted(self):
        result = handle_mood(_update('10'), _context({'name': 'A'}))
        assert result == CHECK_IN_TEXT

    def test_zero_is_rejected(self):
        result = handle_mood(_update('0'), _context())
        assert result == CHECK_IN_MOOD

    def test_eleven_is_rejected(self):
        result = handle_mood(_update('11'), _context())
        assert result == CHECK_IN_MOOD

    def test_non_digit_is_rejected(self):
        result = handle_mood(_update('bad'), _context())
        assert result == CHECK_IN_MOOD

    def test_float_is_rejected(self):
        result = handle_mood(_update('7.5'), _context())
        assert result == CHECK_IN_MOOD

    def test_empty_string_is_rejected(self):
        result = handle_mood(_update(''), _context())
        assert result == CHECK_IN_MOOD
