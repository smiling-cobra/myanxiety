"""Tests for handler input validation.

Strategy: call handler functions directly with mocked Update / CallbackContext
and assert the returned conversation-state integer. No Telegram API is hit.
LLM and DB calls are patched wherever a handler reaches them.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from bot.handlers.journal import (
    CHECK_IN_GUIDANCE_OFFER,
    CHECK_IN_MOOD,
    CHECK_IN_TEXT,
    MAIN_MENU,
    ONBOARDING_TIME,
    ONBOARDING_TIMEZONE,
    handle_entry_text,
    handle_guidance_offer,
    handle_mood,
    handle_reminder_time,
    handle_timezone,
    handle_timezone_location,
    show_history,
    show_stats,
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

    def test_valid_iana_timezone_removes_keyboard(self):
        from telegram import ReplyKeyboardRemove
        update = _update('Europe/London')
        handle_timezone(update, _context({'name': 'Alice'}))
        assert any(
            isinstance(call.kwargs.get('reply_markup'), ReplyKeyboardRemove)
            for call in update.message.reply_text.call_args_list
        )

    def test_city_name_single_match_removes_keyboard(self):
        from telegram import ReplyKeyboardRemove
        update = _update('London')
        handle_timezone(update, _context({'name': 'Alice'}))
        assert any(
            isinstance(call.kwargs.get('reply_markup'), ReplyKeyboardRemove)
            for call in update.message.reply_text.call_args_list
        )

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

    def test_valid_location_removes_keyboard(self):
        from telegram import ReplyKeyboardRemove
        update = _location_update(52.52, 13.405)
        with patch('bot.handlers.journal._tf') as mock_tf:
            mock_tf.timezone_at.return_value = 'Europe/Berlin'
            handle_timezone_location(update, _context({'name': 'Alice'}))
        assert any(
            isinstance(call.kwargs.get('reply_markup'), ReplyKeyboardRemove)
            for call in update.message.reply_text.call_args_list
        )

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


# ---------------------------------------------------------------------------
# Phase 5 — check-in error handling
# ---------------------------------------------------------------------------

class TestHandleEntryTextErrors:
    def _ctx(self, mood_score: int = 7) -> MagicMock:
        return _context({'name': 'Alice', 'mood_score': mood_score})

    def test_db_error_returns_main_menu(self):
        ctx = self._ctx()
        with patch('bot.handlers.journal._journal_svc') as mock_svc, \
             patch('bot.handlers.journal._llm_svc'):
            mock_svc.save_entry.side_effect = Exception('DB down')
            result = handle_entry_text(_update('feeling bad'), ctx)
        assert result == MAIN_MENU

    def test_db_error_sends_error_message(self):
        ctx = self._ctx()
        update = _update('feeling bad')
        with patch('bot.handlers.journal._journal_svc') as mock_svc, \
             patch('bot.handlers.journal._llm_svc'):
            mock_svc.save_entry.side_effect = Exception('DB down')
            handle_entry_text(update, ctx)
        from messages.strings import ERROR_GENERIC
        assert update.message.reply_text.call_args.args[0] == ERROR_GENERIC


class TestShowHistory:
    def test_empty_history_returns_main_menu(self):
        with patch('bot.handlers.journal._journal_svc') as mock_svc:
            mock_svc.get_recent_entries.return_value = []
            result = show_history(_update(''), _context())
        assert result == MAIN_MENU

    def test_db_error_returns_main_menu(self):
        with patch('bot.handlers.journal._journal_svc') as mock_svc:
            mock_svc.get_recent_entries.side_effect = Exception('DB down')
            result = show_history(_update(''), _context())
        assert result == MAIN_MENU

    def test_db_error_sends_error_message(self):
        update = _update('')
        with patch('bot.handlers.journal._journal_svc') as mock_svc:
            mock_svc.get_recent_entries.side_effect = Exception('DB down')
            show_history(update, _context())
        from messages.strings import ERROR_GENERIC
        assert update.message.reply_text.call_args.args[0] == ERROR_GENERIC


class TestShowStats:
    def test_no_entries_returns_main_menu(self):
        with patch('bot.handlers.journal._journal_svc') as mock_svc:
            mock_svc.get_stats.return_value = {'total': 0, 'streak': 0, 'avg_mood': 0}
            mock_svc.get_recent_entries.return_value = []
            result = show_stats(_update(''), _context())
        assert result == MAIN_MENU

    def test_db_error_returns_main_menu(self):
        with patch('bot.handlers.journal._journal_svc') as mock_svc:
            mock_svc.get_stats.side_effect = Exception('DB down')
            result = show_stats(_update(''), _context())
        assert result == MAIN_MENU

    def test_db_error_sends_error_message(self):
        update = _update('')
        with patch('bot.handlers.journal._journal_svc') as mock_svc:
            mock_svc.get_stats.side_effect = Exception('DB down')
            show_stats(update, _context())
        from messages.strings import ERROR_GENERIC
        assert update.message.reply_text.call_args.args[0] == ERROR_GENERIC


# ---------------------------------------------------------------------------
# Phase 6 — guidance offer trigger
# ---------------------------------------------------------------------------

class TestHandleEntryTextGuidance:
    def _run(self, mood_score: int) -> tuple:
        ctx = _context({'name': 'Alice', 'mood_score': mood_score})
        update = _update('I feel awful')
        with patch('bot.handlers.journal._journal_svc') as mock_svc, \
             patch('bot.handlers.journal._llm_svc') as mock_llm:
            mock_svc.get_stats.return_value = {'streak': 1, 'total': 1, 'avg_mood': mood_score}
            mock_llm.extract_tags.return_value = []
            mock_llm.get_empathetic_response.return_value = 'Hang in there.'
            result = handle_entry_text(update, ctx)
        return result, ctx

    def test_score_5_returns_main_menu(self):
        result, _ = self._run(5)
        assert result == MAIN_MENU

    def test_score_10_returns_main_menu(self):
        result, _ = self._run(10)
        assert result == MAIN_MENU

    def test_score_4_triggers_guidance_offer(self):
        result, _ = self._run(4)
        assert result == CHECK_IN_GUIDANCE_OFFER

    def test_score_3_triggers_guidance_offer(self):
        result, _ = self._run(3)
        assert result == CHECK_IN_GUIDANCE_OFFER

    def test_score_1_triggers_guidance_offer(self):
        result, _ = self._run(1)
        assert result == CHECK_IN_GUIDANCE_OFFER

    def test_low_mood_stores_entry_text(self):
        _, ctx = self._run(3)
        assert ctx.user_data.get('entry_text') == 'I feel awful'

    def test_high_mood_does_not_store_entry_text(self):
        _, ctx = self._run(7)
        assert 'entry_text' not in ctx.user_data


# ---------------------------------------------------------------------------
# Phase 6 — guidance offer handler
# ---------------------------------------------------------------------------

class TestHandleGuidanceOffer:
    def _ctx(self, mood_score: int = 3) -> MagicMock:
        return _context({'mood_score': mood_score, 'entry_text': 'feeling rough', 'name': 'Alice'})

    def test_yes_returns_main_menu(self):
        from bot.keyboards import GUIDANCE_YES
        with patch('bot.handlers.journal._llm_svc') as mock_llm:
            mock_llm.get_psychological_guidance.return_value = 'Try deep breathing.'
            result = handle_guidance_offer(_update(GUIDANCE_YES), self._ctx())
        assert result == MAIN_MENU

    def test_yes_calls_llm(self):
        from bot.keyboards import GUIDANCE_YES
        with patch('bot.handlers.journal._llm_svc') as mock_llm:
            mock_llm.get_psychological_guidance.return_value = 'Try deep breathing.'
            handle_guidance_offer(_update(GUIDANCE_YES), self._ctx())
        mock_llm.get_psychological_guidance.assert_called_once_with(3, 'feeling rough')

    def test_no_returns_main_menu(self):
        from bot.keyboards import GUIDANCE_NO
        result = handle_guidance_offer(_update(GUIDANCE_NO), self._ctx())
        assert result == MAIN_MENU

    def test_no_skips_llm(self):
        from bot.keyboards import GUIDANCE_NO
        with patch('bot.handlers.journal._llm_svc') as mock_llm:
            handle_guidance_offer(_update(GUIDANCE_NO), self._ctx())
        mock_llm.get_psychological_guidance.assert_not_called()

    def test_any_other_text_treated_as_decline(self):
        result = handle_guidance_offer(_update('random text'), self._ctx())
        assert result == MAIN_MENU

    def test_very_low_mood_appends_crisis_resources(self):
        from bot.keyboards import GUIDANCE_YES
        from messages.strings import GUIDANCE_CRISIS_RESOURCES
        update = _update(GUIDANCE_YES)
        with patch('bot.handlers.journal._llm_svc') as mock_llm:
            mock_llm.get_psychological_guidance.return_value = 'Try cold water.'
            handle_guidance_offer(update, self._ctx(mood_score=2))
        sent_text = update.message.reply_text.call_args.args[0]
        assert GUIDANCE_CRISIS_RESOURCES in sent_text

    def test_score_3_does_not_append_crisis_resources(self):
        from bot.keyboards import GUIDANCE_YES
        from messages.strings import GUIDANCE_CRISIS_RESOURCES
        update = _update(GUIDANCE_YES)
        with patch('bot.handlers.journal._llm_svc') as mock_llm:
            mock_llm.get_psychological_guidance.return_value = 'Try deep breathing.'
            handle_guidance_offer(update, self._ctx(mood_score=3))
        sent_text = update.message.reply_text.call_args.args[0]
        assert GUIDANCE_CRISIS_RESOURCES not in sent_text
