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
    handle_timezone_location,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _update(text: str, user_id: int = 12345) -> MagicMock:
    u = MagicMock()
    u.message.text = text
    u.effective_user.id = user_id
    return u


def _location_update(lat: float, lng: float, user_id: int = 12345) -> MagicMock:
    u = MagicMock()
    u.message.location.latitude = lat
    u.message.location.longitude = lng
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
    # --- exact IANA match ---

    def test_valid_iana_timezone_advances_state(self):
        ctx = _context({'name': 'Alice'})
        result = handle_timezone(_update('Europe/London'), ctx)
        assert result == ONBOARDING_TIME

    def test_valid_timezone_stored_in_user_data(self):
        ctx = _context({'name': 'Alice'})
        handle_timezone(_update('America/New_York'), ctx)
        assert ctx.user_data['timezone'] == 'America/New_York'

    def test_utc_is_accepted(self):
        ctx = _context({'name': 'Alice'})
        result = handle_timezone(_update('UTC'), ctx)
        assert result == ONBOARDING_TIME

    # --- fuzzy single-match: auto-accept ---

    def test_city_name_single_match_advances_state(self):
        # "London" uniquely matches Europe/London
        ctx = _context({'name': 'Alice'})
        result = handle_timezone(_update('London'), ctx)
        assert result == ONBOARDING_TIME

    def test_city_name_single_match_stores_timezone(self):
        ctx = _context({'name': 'Alice'})
        handle_timezone(_update('London'), ctx)
        assert ctx.user_data['timezone'] == 'Europe/London'

    def test_city_name_case_insensitive(self):
        ctx = _context({'name': 'Alice'})
        result = handle_timezone(_update('london'), ctx)
        assert result == ONBOARDING_TIME

    def test_city_name_space_normalized(self):
        # "New York" → needle "new_york" → America/New_York
        ctx = _context({'name': 'Alice'})
        result = handle_timezone(_update('New York'), ctx)
        assert result == ONBOARDING_TIME
        assert ctx.user_data['timezone'] == 'America/New_York'

    # --- fuzzy multi-match (2-5): show keyboard, stay ---

    def test_city_name_multiple_matches_stays_on_timezone(self):
        # "Kentucky" matches America/Kentucky/Louisville and America/Kentucky/Monticello
        result = handle_timezone(_update('Kentucky'), _context({'name': 'Alice'}))
        assert result == ONBOARDING_TIMEZONE

    # --- no match or too many matches: error, stay ---

    def test_unknown_input_stays_on_timezone(self):
        result = handle_timezone(_update('Mars/Olympus'), _context({'name': 'Alice'}))
        assert result == ONBOARDING_TIMEZONE

    def test_too_many_matches_stays_on_timezone(self):
        # "north" appears in many zone names (>5)
        result = handle_timezone(_update('north'), _context({'name': 'Alice'}))
        assert result == ONBOARDING_TIMEZONE


# ---------------------------------------------------------------------------
# Timezone via location sharing
# ---------------------------------------------------------------------------

class TestHandleTimezoneLocation:
    def test_valid_location_advances_state(self):
        ctx = _context({'name': 'Alice'})
        with patch('bot.handlers.journal._tf') as mock_tf:
            mock_tf.timezone_at.return_value = 'Europe/Berlin'
            result = handle_timezone_location(_location_update(52.52, 13.405), ctx)
        assert result == ONBOARDING_TIME

    def test_valid_location_stores_timezone(self):
        ctx = _context({'name': 'Alice'})
        with patch('bot.handlers.journal._tf') as mock_tf:
            mock_tf.timezone_at.return_value = 'Europe/Berlin'
            handle_timezone_location(_location_update(52.52, 13.405), ctx)
        assert ctx.user_data['timezone'] == 'Europe/Berlin'

    def test_unresolvable_location_stays_on_timezone(self):
        # timezonefinder returns None for open ocean coordinates
        ctx = _context({'name': 'Alice'})
        with patch('bot.handlers.journal._tf') as mock_tf:
            mock_tf.timezone_at.return_value = None
            result = handle_timezone_location(_location_update(0.0, 0.0), ctx)
        assert result == ONBOARDING_TIMEZONE

    def test_unresolvable_location_does_not_store_timezone(self):
        ctx = _context({'name': 'Alice'})
        with patch('bot.handlers.journal._tf') as mock_tf:
            mock_tf.timezone_at.return_value = None
            handle_timezone_location(_location_update(0.0, 0.0), ctx)
        assert 'timezone' not in ctx.user_data


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
