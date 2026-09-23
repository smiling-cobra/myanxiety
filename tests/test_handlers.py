"""Tests for handler input validation.

Strategy: call handler functions directly with mocked Update / CallbackContext
and assert the returned conversation-state integer. No Telegram API is hit.
LLM and DB calls are patched wherever a handler reaches them.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from datetime import datetime

from bot.handlers.journal import (
    CHECK_IN_GUIDANCE_OFFER,
    CHECK_IN_MOOD,
    CHECK_IN_TEXT,
    MAIN_MENU,
    ONBOARDING_NAME,
    ONBOARDING_THERAPY,
    ONBOARDING_TIME,
    ONBOARDING_TIMEZONE,
    handle_entry_text,
    handle_guidance_offer,
    handle_mood,
    handle_reminder_time,
    handle_therapy,
    handle_timezone,
    handle_timezone_location,
    recover_state,
    show_history,
    show_stats,
    show_weekly_summary,
    start,
)
from bot.handlers.journal.views import mood_bar
from messages.strings import GUIDANCE_CRISIS_RESOURCES
from repositories.user_repo import UserRepository
from tests.conftest import make_context as _context, make_location_update as _location_update, make_update as _update


def _set_user_timezone(name: str, user_id: int = 12345) -> None:
    UserRepository().save({'telegram_id': user_id, 'timezone': name, 'onboarded': True})


async def _history_text(created_at: datetime = datetime(2026, 3, 26, 11, 0)) -> str:
    """Render the history view for a single entry stored at the given UTC instant."""
    update = _update('')
    with patch('bot.handlers.journal.deps.journal_svc') as mock_svc:
        mock_svc.get_recent_entries.return_value = [
            {'mood_score': 5, 'text': 'late night', 'tags': [], 'created_at': created_at}
        ]
        await show_history(update, _context())
    return update.message.reply_text.call_args.args[0]


# ---------------------------------------------------------------------------
# Timezone validation
# ---------------------------------------------------------------------------

class TestHandleTimezone:
    # --- exact IANA match ---

    async def test_valid_iana_timezone_advances_state(self):
        ctx = _context({'name': 'Alice'})
        result = await handle_timezone(_update('Europe/London'), ctx)
        assert result == ONBOARDING_TIME

    async def test_valid_timezone_stored_in_user_data(self):
        ctx = _context({'name': 'Alice'})
        await handle_timezone(_update('America/New_York'), ctx)
        assert ctx.user_data['timezone'] == 'America/New_York'

    async def test_utc_is_accepted(self):
        ctx = _context({'name': 'Alice'})
        result = await handle_timezone(_update('UTC'), ctx)
        assert result == ONBOARDING_TIME

    # --- fuzzy single-match: auto-accept ---

    async def test_city_name_single_match_advances_state(self):
        # "London" uniquely matches Europe/London
        ctx = _context({'name': 'Alice'})
        result = await handle_timezone(_update('London'), ctx)
        assert result == ONBOARDING_TIME

    async def test_city_name_single_match_stores_timezone(self):
        ctx = _context({'name': 'Alice'})
        await handle_timezone(_update('London'), ctx)
        assert ctx.user_data['timezone'] == 'Europe/London'

    async def test_city_name_case_insensitive(self):
        ctx = _context({'name': 'Alice'})
        result = await handle_timezone(_update('london'), ctx)
        assert result == ONBOARDING_TIME

    async def test_city_name_space_normalized(self):
        # "New York" → needle "new_york" → America/New_York
        ctx = _context({'name': 'Alice'})
        result = await handle_timezone(_update('New York'), ctx)
        assert result == ONBOARDING_TIME
        assert ctx.user_data['timezone'] == 'America/New_York'

    async def test_valid_iana_timezone_removes_keyboard(self):
        from telegram import ReplyKeyboardRemove
        update = _update('Europe/London')
        await handle_timezone(update, _context({'name': 'Alice'}))
        assert any(
            isinstance(call.kwargs.get('reply_markup'), ReplyKeyboardRemove)
            for call in update.message.reply_text.call_args_list
        )

    async def test_city_name_single_match_removes_keyboard(self):
        from telegram import ReplyKeyboardRemove
        update = _update('London')
        await handle_timezone(update, _context({'name': 'Alice'}))
        assert any(
            isinstance(call.kwargs.get('reply_markup'), ReplyKeyboardRemove)
            for call in update.message.reply_text.call_args_list
        )

    # --- fuzzy multi-match (2-5): show keyboard, stay ---

    async def test_city_name_multiple_matches_stays_on_timezone(self):
        # "Kentucky" matches America/Kentucky/Louisville and America/Kentucky/Monticello
        result = await handle_timezone(_update('Kentucky'), _context({'name': 'Alice'}))
        assert result == ONBOARDING_TIMEZONE

    # --- no match or too many matches: error, stay ---

    async def test_unknown_input_stays_on_timezone(self):
        result = await handle_timezone(_update('Mars/Olympus'), _context({'name': 'Alice'}))
        assert result == ONBOARDING_TIMEZONE

    async def test_too_many_matches_stays_on_timezone(self):
        # "north" appears in many zone names (>5)
        result = await handle_timezone(_update('north'), _context({'name': 'Alice'}))
        assert result == ONBOARDING_TIMEZONE


# ---------------------------------------------------------------------------
# Timezone via location sharing
# ---------------------------------------------------------------------------

class TestHandleTimezoneLocation:
    async def test_valid_location_advances_state(self):
        ctx = _context({'name': 'Alice'})
        with patch('bot.handlers.journal.timezones._tf') as mock_tf:
            mock_tf.timezone_at.return_value = 'Europe/Berlin'
            result = await handle_timezone_location(_location_update(52.52, 13.405), ctx)
        assert result == ONBOARDING_TIME

    async def test_valid_location_stores_timezone(self):
        ctx = _context({'name': 'Alice'})
        with patch('bot.handlers.journal.timezones._tf') as mock_tf:
            mock_tf.timezone_at.return_value = 'Europe/Berlin'
            await handle_timezone_location(_location_update(52.52, 13.405), ctx)
        assert ctx.user_data['timezone'] == 'Europe/Berlin'

    async def test_valid_location_removes_keyboard(self):
        from telegram import ReplyKeyboardRemove
        update = _location_update(52.52, 13.405)
        with patch('bot.handlers.journal.timezones._tf') as mock_tf:
            mock_tf.timezone_at.return_value = 'Europe/Berlin'
            await handle_timezone_location(update, _context({'name': 'Alice'}))
        assert any(
            isinstance(call.kwargs.get('reply_markup'), ReplyKeyboardRemove)
            for call in update.message.reply_text.call_args_list
        )

    async def test_unresolvable_location_stays_on_timezone(self):
        # timezonefinder returns None for open ocean coordinates
        ctx = _context({'name': 'Alice'})
        with patch('bot.handlers.journal.timezones._tf') as mock_tf:
            mock_tf.timezone_at.return_value = None
            result = await handle_timezone_location(_location_update(0.0, 0.0), ctx)
        assert result == ONBOARDING_TIMEZONE

    async def test_unresolvable_location_does_not_store_timezone(self):
        ctx = _context({'name': 'Alice'})
        with patch('bot.handlers.journal.timezones._tf') as mock_tf:
            mock_tf.timezone_at.return_value = None
            await handle_timezone_location(_location_update(0.0, 0.0), ctx)
        assert 'timezone' not in ctx.user_data


# ---------------------------------------------------------------------------
# Reminder time validation
# ---------------------------------------------------------------------------

class TestHandleReminderTime:
    def _ctx(self) -> MagicMock:
        return _context({'name': 'Alice', 'timezone': 'Europe/London'})

    async def test_valid_time_advances_to_the_cohort_question(self):
        with patch('bot.handlers.journal.deps.user_svc'):
            result = await handle_reminder_time(_update('09:00'), self._ctx())
        assert result == ONBOARDING_THERAPY

    async def test_valid_time_saves_user(self):
        with patch('bot.handlers.journal.deps.user_svc') as mock_svc:
            await handle_reminder_time(_update('21:30'), self._ctx())
        mock_svc.create_or_update.assert_called_once()

    async def test_no_colon_stays(self):
        result = await handle_reminder_time(_update('0900'), self._ctx())
        assert result == ONBOARDING_TIME

    async def test_letters_stay(self):
        result = await handle_reminder_time(_update('nine'), self._ctx())
        assert result == ONBOARDING_TIME

    async def test_hour_25_stays(self):
        result = await handle_reminder_time(_update('25:00'), self._ctx())
        assert result == ONBOARDING_TIME

    async def test_minute_60_stays(self):
        result = await handle_reminder_time(_update('09:60'), self._ctx())
        assert result == ONBOARDING_TIME

    async def test_boundary_midnight(self):
        with patch('bot.handlers.journal.deps.user_svc'):
            result = await handle_reminder_time(_update('00:00'), self._ctx())
        assert result == ONBOARDING_THERAPY

    async def test_boundary_last_minute_of_day(self):
        with patch('bot.handlers.journal.deps.user_svc'):
            result = await handle_reminder_time(_update('23:59'), self._ctx())
        assert result == ONBOARDING_THERAPY

    async def test_account_is_onboarded_before_the_optional_question(self):
        """Abandoning the cohort question must not leave a half-created account."""
        with patch('bot.handlers.journal.deps.user_svc') as mock_svc:
            await handle_reminder_time(_update('09:00'), self._ctx())
        assert mock_svc.create_or_update.call_args.kwargs['onboarded'] is True


# ---------------------------------------------------------------------------
# Mood score validation
# ---------------------------------------------------------------------------

class TestHandleMood:
    async def test_valid_score_advances_state(self):
        ctx = _context({'name': 'Alice'})
        result = await handle_mood(_update('7'), ctx)
        assert result == CHECK_IN_TEXT

    async def test_score_stored_in_user_data(self):
        ctx = _context({'name': 'Alice'})
        await handle_mood(_update('7'), ctx)
        assert ctx.user_data['mood_score'] == 7

    async def test_lower_boundary_accepted(self):
        result = await handle_mood(_update('1'), _context({'name': 'A'}))
        assert result == CHECK_IN_TEXT

    async def test_upper_boundary_accepted(self):
        result = await handle_mood(_update('10'), _context({'name': 'A'}))
        assert result == CHECK_IN_TEXT

    async def test_zero_is_rejected(self):
        result = await handle_mood(_update('0'), _context())
        assert result == CHECK_IN_MOOD

    async def test_eleven_is_rejected(self):
        result = await handle_mood(_update('11'), _context())
        assert result == CHECK_IN_MOOD

    async def test_non_digit_is_rejected(self):
        result = await handle_mood(_update('bad'), _context())
        assert result == CHECK_IN_MOOD

    async def test_float_is_rejected(self):
        result = await handle_mood(_update('7.5'), _context())
        assert result == CHECK_IN_MOOD

    async def test_empty_string_is_rejected(self):
        result = await handle_mood(_update(''), _context())
        assert result == CHECK_IN_MOOD


# ---------------------------------------------------------------------------
# Phase 5 — check-in error handling
# ---------------------------------------------------------------------------

class TestHandleEntryTextErrors:
    def _ctx(self, mood_score: int = 7) -> MagicMock:
        return _context({'name': 'Alice', 'mood_score': mood_score})

    async def test_db_error_returns_main_menu(self):
        ctx = self._ctx()
        with patch('bot.handlers.journal.deps.journal_svc') as mock_svc, \
             patch('bot.handlers.journal.deps.llm_svc'):
            mock_svc.save_entry.side_effect = Exception('DB down')
            result = await handle_entry_text(_update('feeling bad'), ctx)
        assert result == MAIN_MENU

    async def test_db_error_sends_error_message(self):
        ctx = self._ctx()
        update = _update('feeling bad')
        with patch('bot.handlers.journal.deps.journal_svc') as mock_svc, \
             patch('bot.handlers.journal.deps.llm_svc'):
            mock_svc.save_entry.side_effect = Exception('DB down')
            await handle_entry_text(update, ctx)
        from messages.strings import ERROR_GENERIC
        assert update.message.reply_text.call_args.args[0] == ERROR_GENERIC


class TestShowHistory:
    async def test_empty_history_returns_main_menu(self):
        with patch('bot.handlers.journal.deps.journal_svc') as mock_svc:
            mock_svc.get_recent_entries.return_value = []
            result = await show_history(_update(''), _context())
        assert result == MAIN_MENU

    async def test_db_error_returns_main_menu(self):
        with patch('bot.handlers.journal.deps.journal_svc') as mock_svc:
            mock_svc.get_recent_entries.side_effect = Exception('DB down')
            result = await show_history(_update(''), _context())
        assert result == MAIN_MENU

    async def test_db_error_sends_error_message(self):
        update = _update('')
        with patch('bot.handlers.journal.deps.journal_svc') as mock_svc:
            mock_svc.get_recent_entries.side_effect = Exception('DB down')
            await show_history(update, _context())
        from messages.strings import ERROR_GENERIC
        assert update.message.reply_text.call_args.args[0] == ERROR_GENERIC

    async def test_dates_render_in_the_users_timezone(self):
        # Kiritimati is UTC+14, so 11:00 UTC on the 26th is 01:00 on the 27th there.
        _set_user_timezone('Pacific/Kiritimati')
        text = await _history_text()
        assert '27 Mar 2026' in text

    async def test_dates_fall_back_to_utc_without_a_timezone(self):
        text = await _history_text()
        assert '26 Mar 2026' in text


class TestShowStats:
    async def test_no_entries_returns_main_menu(self):
        with patch('bot.handlers.journal.deps.journal_svc') as mock_svc:
            mock_svc.get_stats.return_value = {'total': 0, 'streak': 0, 'avg_mood': 0}
            mock_svc.get_recent_entries.return_value = []
            result = await show_stats(_update(''), _context())
        assert result == MAIN_MENU

    async def test_db_error_returns_main_menu(self):
        with patch('bot.handlers.journal.deps.journal_svc') as mock_svc:
            mock_svc.get_stats.side_effect = Exception('DB down')
            result = await show_stats(_update(''), _context())
        assert result == MAIN_MENU

    async def test_db_error_sends_error_message(self):
        update = _update('')
        with patch('bot.handlers.journal.deps.journal_svc') as mock_svc:
            mock_svc.get_stats.side_effect = Exception('DB down')
            await show_stats(update, _context())
        from messages.strings import ERROR_GENERIC
        assert update.message.reply_text.call_args.args[0] == ERROR_GENERIC

    async def test_tag_variants_are_counted_as_one_theme(self):
        update = _update('')
        with patch('bot.handlers.journal.deps.journal_svc') as mock_svc:
            mock_svc.get_stats.return_value = {'total': 3, 'streak': 1, 'avg_mood': 5}
            mock_svc.get_recent_entries.return_value = [
                {'tags': ['job']}, {'tags': ['Work']}, {'tags': ['work stress', 'sleep']},
            ]
            await show_stats(update, _context())
        text = update.message.reply_text.call_args.args[0]
        assert 'Top tags: #work, #sleep' in text
        assert 'job' not in text


# ---------------------------------------------------------------------------
# Phase 4 — mood bar helper
# ---------------------------------------------------------------------------

class TestMoodBar:
    def test_score_0_all_empty(self):
        assert mood_bar(0) == '░░░░░░░░░░'

    def test_score_10_all_filled(self):
        assert mood_bar(10) == '▓▓▓▓▓▓▓▓▓▓'

    def test_score_5_half_filled(self):
        assert mood_bar(5) == '▓▓▓▓▓░░░░░'

    def test_total_length_always_10(self):
        for score in range(0, 11):
            assert len(mood_bar(score)) == 10

    def test_clamps_below_zero(self):
        assert mood_bar(-1) == '░░░░░░░░░░'

    def test_clamps_above_ten(self):
        assert mood_bar(11) == '▓▓▓▓▓▓▓▓▓▓'


# ---------------------------------------------------------------------------
# Phase 4 — weekly summary
# ---------------------------------------------------------------------------

def _entry(mood: int, days_ago: int = 0) -> dict:
    return {
        'mood_score': mood,
        'text': 'entry text',
        'tags': ['work', 'stress'],
        'created_at': datetime(2026, 3, 29 - days_ago, 10, 0),
    }


class TestShowWeeklySummary:
    async def test_no_entries_returns_main_menu(self):
        with patch('bot.handlers.journal.deps.journal_svc') as mock_svc:
            mock_svc.get_weekly_entries.return_value = []
            result = await show_weekly_summary(_update(''), _context())
        assert result == MAIN_MENU

    async def test_no_entries_sends_empty_message(self):
        update = _update('')
        with patch('bot.handlers.journal.deps.journal_svc') as mock_svc:
            mock_svc.get_weekly_entries.return_value = []
            await show_weekly_summary(update, _context())
        from messages.strings import WEEKLY_SUMMARY_EMPTY
        assert update.message.reply_text.call_args.args[0] == WEEKLY_SUMMARY_EMPTY

    async def test_with_entries_returns_main_menu(self):
        with patch('bot.handlers.journal.deps.journal_svc') as mock_svc, \
             patch('bot.handlers.journal.deps.llm_svc') as mock_llm:
            mock_svc.get_weekly_entries.return_value = [_entry(7), _entry(5, 1), _entry(3, 2)]
            mock_llm.get_weekly_summary.return_value = 'A good week overall.'
            result = await show_weekly_summary(_update(''), _context())
        assert result == MAIN_MENU

    async def test_message_contains_mood_scores(self):
        update = _update('')
        with patch('bot.handlers.journal.deps.journal_svc') as mock_svc, \
             patch('bot.handlers.journal.deps.llm_svc') as mock_llm:
            mock_svc.get_weekly_entries.return_value = [_entry(7), _entry(5, 1)]
            mock_llm.get_weekly_summary.return_value = 'Summary.'
            await show_weekly_summary(update, _context())
        text = update.message.reply_text.call_args.args[0]
        assert '7' in text
        assert '5' in text

    async def test_message_contains_mood_bar(self):
        update = _update('')
        with patch('bot.handlers.journal.deps.journal_svc') as mock_svc, \
             patch('bot.handlers.journal.deps.llm_svc') as mock_llm:
            mock_svc.get_weekly_entries.return_value = [_entry(5)]
            mock_llm.get_weekly_summary.return_value = 'Summary.'
            await show_weekly_summary(update, _context())
        text = update.message.reply_text.call_args.args[0]
        assert '▓' in text

    async def test_enough_entries_calls_llm_summary(self):
        with patch('bot.handlers.journal.deps.journal_svc') as mock_svc, \
             patch('bot.handlers.journal.deps.llm_svc') as mock_llm:
            mock_svc.get_weekly_entries.return_value = [_entry(7), _entry(5, 1), _entry(3, 2)]
            mock_llm.get_weekly_summary.return_value = 'Summary.'
            await show_weekly_summary(_update(''), _context())
        mock_llm.get_weekly_summary.assert_called_once()

    async def test_too_few_entries_skips_llm_summary(self):
        update = _update('')
        with patch('bot.handlers.journal.deps.journal_svc') as mock_svc, \
             patch('bot.handlers.journal.deps.llm_svc') as mock_llm:
            mock_svc.get_weekly_entries.return_value = [_entry(5), _entry(4, 1)]
            await show_weekly_summary(update, _context())
        mock_llm.get_weekly_summary.assert_not_called()
        from messages.strings import WEEKLY_SUMMARY_TOO_FEW
        assert WEEKLY_SUMMARY_TOO_FEW in update.message.reply_text.call_args.args[0]

    async def test_db_error_returns_main_menu(self):
        with patch('bot.handlers.journal.deps.journal_svc') as mock_svc:
            mock_svc.get_weekly_entries.side_effect = Exception('DB down')
            result = await show_weekly_summary(_update(''), _context())
        assert result == MAIN_MENU

    async def test_day_labels_render_in_the_users_timezone(self):
        # Kiritimati is UTC+14: 11:00 UTC on the 26th is the 27th locally.
        _set_user_timezone('Pacific/Kiritimati')
        update = _update('')
        with patch('bot.handlers.journal.deps.journal_svc') as mock_svc, \
             patch('bot.handlers.journal.deps.llm_svc') as mock_llm:
            mock_svc.get_weekly_entries.return_value = [
                {'mood_score': 5, 'text': 'x', 'tags': [],
                 'created_at': datetime(2026, 3, 26, 11, 0)}
            ]
            mock_llm.get_weekly_summary.return_value = 'Summary.'
            await show_weekly_summary(update, _context())
        assert '27 Mar' in update.message.reply_text.call_args.args[0]

    async def test_stored_timezone_is_passed_to_the_query(self):
        _set_user_timezone('Pacific/Kiritimati')
        with patch('bot.handlers.journal.deps.journal_svc') as mock_svc:
            mock_svc.get_weekly_entries.return_value = []
            await show_weekly_summary(_update(''), _context())
        assert mock_svc.get_weekly_entries.call_args.args[1] == 'Pacific/Kiritimati'


# ---------------------------------------------------------------------------
# Phase 6 — guidance offer trigger
# ---------------------------------------------------------------------------

class TestHandleEntryTextGuidance:
    async def _run(self, mood_score: int) -> tuple:
        ctx = _context({'name': 'Alice', 'mood_score': mood_score})
        update = _update('I feel awful')
        with patch('bot.handlers.journal.deps.journal_svc') as mock_svc, \
             patch('bot.handlers.journal.deps.llm_svc') as mock_llm:
            mock_svc.get_stats.return_value = {'streak': 1, 'total': 1, 'avg_mood': mood_score}
            mock_llm.extract_tags.return_value = []
            mock_llm.get_empathetic_response.return_value = 'Hang in there.'
            result = await handle_entry_text(update, ctx)
        return result, ctx

    async def test_score_5_returns_main_menu(self):
        result, _ = await self._run(5)
        assert result == MAIN_MENU

    async def test_score_10_returns_main_menu(self):
        result, _ = await self._run(10)
        assert result == MAIN_MENU

    async def test_score_4_triggers_guidance_offer(self):
        result, _ = await self._run(4)
        assert result == CHECK_IN_GUIDANCE_OFFER

    async def test_score_3_triggers_guidance_offer(self):
        result, _ = await self._run(3)
        assert result == CHECK_IN_GUIDANCE_OFFER

    async def test_score_1_triggers_guidance_offer(self):
        result, _ = await self._run(1)
        assert result == CHECK_IN_GUIDANCE_OFFER

    async def test_low_mood_stores_entry_text(self):
        _, ctx = await self._run(3)
        assert ctx.user_data.get('entry_text') == 'I feel awful'

    async def test_high_mood_does_not_store_entry_text(self):
        _, ctx = await self._run(7)
        assert 'entry_text' not in ctx.user_data


# ---------------------------------------------------------------------------
# Crisis-resource delivery guarantee
#
# Resources must reach an acutely low-mood user unconditionally: not behind an
# opt-in, and not downstream of a DB or LLM call that can fail.
# ---------------------------------------------------------------------------

class TestCrisisResourceDelivery:
    def _sent(self, update) -> list:
        return [c.args[0] for c in update.message.reply_text.call_args_list]

    async def _run(self, mood_score: int, svc_error: Exception | None = None) -> MagicMock:
        ctx = _context({'name': 'Alice', 'mood_score': mood_score})
        update = _update('I feel awful')
        with patch('bot.handlers.journal.deps.journal_svc') as mock_svc, \
             patch('bot.handlers.journal.deps.llm_svc') as mock_llm:
            if svc_error is not None:
                mock_llm.extract_tags.side_effect = svc_error
            else:
                mock_llm.extract_tags.return_value = []
            mock_svc.get_stats.return_value = {'streak': 1, 'total': 1, 'avg_mood': mood_score}
            mock_llm.get_empathetic_response.return_value = 'Hang in there.'
            await handle_entry_text(update, ctx)
        return update

    async def test_score_2_receives_crisis_resources(self):
        update = await self._run(2)
        assert GUIDANCE_CRISIS_RESOURCES in self._sent(update)

    async def test_score_1_receives_crisis_resources(self):
        update = await self._run(1)
        assert GUIDANCE_CRISIS_RESOURCES in self._sent(update)

    async def test_score_3_does_not_receive_crisis_resources(self):
        update = await self._run(3)
        assert GUIDANCE_CRISIS_RESOURCES not in self._sent(update)

    async def test_delivered_even_when_the_check_in_fails(self):
        """The regression this fix exists for: a Mongo or LLM failure used to
        return ERROR_GENERIC and MAIN_MENU, skipping the crisis path entirely."""
        update = await self._run(1, svc_error=Exception('DB down'))
        assert GUIDANCE_CRISIS_RESOURCES in self._sent(update)

    async def test_delivered_before_anything_that_can_fail(self):
        update = await self._run(1)
        assert self._sent(update)[0] == GUIDANCE_CRISIS_RESOURCES

    def test_help_message_carries_crisis_resources(self):
        """/help is reachable mid-conversation, so it is the escape hatch that
        survives lost conversation state."""
        from messages.strings import HELP_MESSAGE
        assert 'iasp.info' in HELP_MESSAGE
        assert '116 123' in HELP_MESSAGE


# ---------------------------------------------------------------------------
# Consent notice
#
# Entry text leaves the product for a third-party API. That has to be disclosed
# before the first entry is written, and stay reachable afterwards.
# ---------------------------------------------------------------------------

class TestPrivacyNotice:
    async def test_new_user_sees_it_before_being_asked_anything(self):
        from messages.strings import PRIVACY_NOTICE
        update = _update('/start')
        with patch('bot.handlers.journal.deps.user_svc') as mock_svc:
            mock_svc.get.return_value = None
            result = await start(update, _context())
        sent = [c.args[0] for c in update.message.reply_text.call_args_list]
        assert PRIVACY_NOTICE in sent
        assert result == ONBOARDING_NAME

    async def test_returning_user_is_not_shown_it_again(self):
        from messages.strings import PRIVACY_NOTICE
        update = _update('/start')
        with patch('bot.handlers.journal.deps.user_svc') as mock_svc:
            mock_svc.get.return_value = {'name': 'Alice', 'onboarded': True}
            result = await start(update, _context())
        sent = [c.args[0] for c in update.message.reply_text.call_args_list]
        assert PRIVACY_NOTICE not in sent
        assert result == MAIN_MENU

    async def test_privacy_command_repeats_it(self):
        from bot.handlers.commands import privacy_command
        from messages.strings import PRIVACY_NOTICE
        update = _update('/privacy')
        await privacy_command(update, _context())
        assert update.message.reply_text.call_args.args[0] == PRIVACY_NOTICE

    def test_help_points_at_it(self):
        from messages.strings import HELP_MESSAGE
        assert '/privacy' in HELP_MESSAGE

    def test_the_notice_says_the_export_is_shared_only_by_the_user(self):
        from messages.strings import PRIVACY_NOTICE
        assert 'nobody sees it unless you send it to them yourself' in PRIVACY_NOTICE

    def test_welcome_makes_no_treatment_claim(self):
        """Copy decides whether this reads as a wellness tool or a medical one."""
        from messages.strings import ONBOARDING_WELCOME
        for claim in ('help you', 'treat', 'heal', 'therapy for', 'anxiety'):
            assert claim not in ONBOARDING_WELCOME.lower()

    def test_welcome_makes_no_bare_privacy_claim(self):
        """The bot forwards entry text to a third-party API, so 'private
        anxiety journal' was an inaccurate opening line, not just a legal gap."""
        from messages.strings import ONBOARDING_WELCOME
        assert 'private' not in ONBOARDING_WELCOME.lower()


# ---------------------------------------------------------------------------
# Fail-closed handling of a missing mood score
# ---------------------------------------------------------------------------

class TestMissingMoodScore:
    async def test_entry_text_re_asks_instead_of_assuming(self):
        update = _update('I feel awful')
        with patch('bot.handlers.journal.deps.journal_svc') as mock_svc, \
             patch('bot.handlers.journal.deps.llm_svc') as mock_llm:
            result = await handle_entry_text(update, _context({'name': 'Alice'}))
        assert result == CHECK_IN_MOOD
        mock_svc.save_entry.assert_not_called()
        mock_llm.extract_tags.assert_not_called()

    async def test_entry_text_tells_the_user_it_was_not_saved(self):
        from messages.strings import MOOD_LOST
        update = _update('I feel awful')
        with patch('bot.handlers.journal.deps.journal_svc'), \
             patch('bot.handlers.journal.deps.llm_svc'):
            await handle_entry_text(update, _context({'name': 'Alice'}))
        assert update.message.reply_text.call_args.args[0] == MOOD_LOST

    async def test_guidance_offer_shows_crisis_resources(self):
        """This state is only reachable from a low-mood check-in, so a missing
        score means lost state rather than a well user."""
        from bot.keyboards import GUIDANCE_NO
        update = _update(GUIDANCE_NO)
        with patch('bot.handlers.journal.deps.llm_svc'):
            result = await handle_guidance_offer(update, _context({'entry_text': 'rough'}))
        sent = [c.args[0] for c in update.message.reply_text.call_args_list]
        assert GUIDANCE_CRISIS_RESOURCES in sent
        assert result == MAIN_MENU


# ---------------------------------------------------------------------------
# Phase 6 — guidance offer handler
# ---------------------------------------------------------------------------

class TestHandleGuidanceOffer:
    def _ctx(self, mood_score: int = 3) -> MagicMock:
        return _context({'mood_score': mood_score, 'entry_text': 'feeling rough', 'name': 'Alice'})

    async def test_yes_returns_main_menu(self):
        from bot.keyboards import GUIDANCE_YES
        with patch('bot.handlers.journal.deps.llm_svc') as mock_llm:
            mock_llm.get_psychological_guidance.return_value = 'Try deep breathing.'
            result = await handle_guidance_offer(_update(GUIDANCE_YES), self._ctx())
        assert result == MAIN_MENU

    async def test_yes_calls_llm(self):
        from bot.keyboards import GUIDANCE_YES
        with patch('bot.handlers.journal.deps.llm_svc') as mock_llm:
            mock_llm.get_psychological_guidance.return_value = 'Try deep breathing.'
            await handle_guidance_offer(_update(GUIDANCE_YES), self._ctx())
        mock_llm.get_psychological_guidance.assert_called_once_with(3, 'feeling rough')

    async def test_no_returns_main_menu(self):
        from bot.keyboards import GUIDANCE_NO
        result = await handle_guidance_offer(_update(GUIDANCE_NO), self._ctx())
        assert result == MAIN_MENU

    async def test_no_skips_llm(self):
        from bot.keyboards import GUIDANCE_NO
        with patch('bot.handlers.journal.deps.llm_svc') as mock_llm:
            await handle_guidance_offer(_update(GUIDANCE_NO), self._ctx())
        mock_llm.get_psychological_guidance.assert_not_called()

    async def test_any_other_text_treated_as_decline(self):
        result = await handle_guidance_offer(_update('random text'), self._ctx())
        assert result == MAIN_MENU

    async def test_crisis_resources_are_not_repeated_here(self):
        """handle_entry_text now delivers them unconditionally at mood <= 2,
        before this opt-in is ever offered. See TestCrisisResourceDelivery."""
        from bot.keyboards import GUIDANCE_YES
        update = _update(GUIDANCE_YES)
        with patch('bot.handlers.journal.deps.llm_svc') as mock_llm:
            mock_llm.get_psychological_guidance.return_value = 'Try cold water.'
            await handle_guidance_offer(update, self._ctx(mood_score=2))
        sent = [c.args[0] for c in update.message.reply_text.call_args_list]
        assert GUIDANCE_CRISIS_RESOURCES not in sent

    async def test_score_3_does_not_append_crisis_resources(self):
        from bot.keyboards import GUIDANCE_YES
        update = _update(GUIDANCE_YES)
        with patch('bot.handlers.journal.deps.llm_svc') as mock_llm:
            mock_llm.get_psychological_guidance.return_value = 'Try deep breathing.'
            await handle_guidance_offer(update, self._ctx(mood_score=3))
        sent_text = update.message.reply_text.call_args.args[0]
        assert GUIDANCE_CRISIS_RESOURCES not in sent_text


# ---------------------------------------------------------------------------
# Lost conversation state
#
# A text message that matches no active conversation. Reached after a restart
# that outlived the stored state, but also after a plain /cancel or a first-ever
# message — indistinguishable from inside the handler.
# ---------------------------------------------------------------------------

class TestRecoverState:
    @staticmethod
    def _onboarded(mock_svc, name: str = 'Sam'):
        mock_svc.get.return_value = {'telegram_id': 12345, 'name': name, 'onboarded': True}

    async def test_unonboarded_user_is_sent_through_onboarding(self):
        with patch('bot.handlers.journal.deps.user_svc') as mock_svc:
            mock_svc.get.return_value = None
            state = await recover_state(_update('hello'), _context())
        assert state == ONBOARDING_NAME

    async def test_half_onboarded_user_is_sent_through_onboarding(self):
        with patch('bot.handlers.journal.deps.user_svc') as mock_svc:
            mock_svc.get.return_value = {'telegram_id': 12345, 'name': 'Sam'}
            state = await recover_state(_update('hello'), _context())
        assert state == ONBOARDING_NAME

    async def test_onboarded_user_lands_back_on_the_main_menu(self):
        update = _update('some stray text')
        with patch('bot.handlers.journal.deps.user_svc') as mock_svc:
            self._onboarded(mock_svc)
            state = await recover_state(update, _context())
        assert state == MAIN_MENU
        assert 'Sam' in update.message.reply_text.call_args.args[0]

    async def test_stray_text_still_gets_an_answer(self):
        """handle_main_menu returns silently for unknown text; recovery must not."""
        update = _update('some stray text')
        with patch('bot.handlers.journal.deps.user_svc') as mock_svc:
            self._onboarded(mock_svc)
            await recover_state(update, _context())
        assert update.message.reply_text.called

    async def test_a_stale_menu_tap_is_acted_on_immediately(self):
        """The keyboard outlives the conversation, so this is the common case:
        the button must work on the first tap, not the second."""
        from bot.keyboards import CHECK_IN
        update = _update(CHECK_IN)
        with patch('bot.handlers.journal.deps.user_svc') as mock_svc:
            self._onboarded(mock_svc)
            state = await recover_state(update, _context())
        assert state == CHECK_IN_MOOD

    async def test_a_stale_add_a_note_tap_is_acted_on_immediately(self):
        from bot.keyboards import ADD_NOTE
        update = _update(ADD_NOTE)
        with patch('bot.handlers.journal.deps.user_svc') as mock_svc:
            self._onboarded(mock_svc)
            state = await recover_state(update, _context())
        assert state == CHECK_IN_MOOD

    async def test_the_name_is_restored_for_later_handlers(self):
        ctx = _context()
        with patch('bot.handlers.journal.deps.user_svc') as mock_svc:
            self._onboarded(mock_svc)
            await recover_state(_update('hello'), ctx)
        assert ctx.user_data['name'] == 'Sam'

    async def test_an_in_memory_name_is_not_overwritten(self):
        ctx = _context({'name': 'Alex'})
        with patch('bot.handlers.journal.deps.user_svc') as mock_svc:
            self._onboarded(mock_svc)
            await recover_state(_update('hello'), ctx)
        assert ctx.user_data['name'] == 'Alex'


# ---------------------------------------------------------------------------
# Migration guard — v20+ requires coroutine callbacks
#
# A handler that is accidentally left synchronous still registers fine and only
# fails when a user reaches it, so assert the shape here instead.
# ---------------------------------------------------------------------------

class TestHandlersAreCoroutines:
    def test_every_registered_handler_is_async(self):
        import inspect
        from bot.handlers import commands, journal

        callbacks = [
            journal.start,
            journal.handle_name,
            journal.handle_timezone,
            journal.handle_timezone_location,
            journal.handle_reminder_time,
            journal.handle_main_menu,
            journal.handle_mood,
            journal.handle_entry_text,
            journal.show_history,
            journal.show_stats,
            journal.show_weekly_summary,
            journal.send_export,
            journal.toggle_flag,
            journal.request_delete,
            journal.handle_delete_confirmation,
            journal.handle_guidance_offer,
            journal.cancel,
            journal.recover_state,
            commands.help_command,
            commands.privacy_command,
        ]
        not_async = [c.__name__ for c in callbacks if not inspect.iscoroutinefunction(c)]
        assert not_async == []

    def test_register_accepts_an_application(self):
        """`dispatcher.add_handler` is gone in v20+; registration goes through
        Application. Passing a mock proves the call shape, not the wiring."""
        from bot.handlers import commands, journal

        app = MagicMock()
        journal.register(app)
        commands.register(app)
        assert app.add_handler.call_count == 3


# ---------------------------------------------------------------------------
# Guard — deps must be reached by attribute, never imported by value
#
# `patch('bot.handlers.journal.deps.llm_svc')` only reaches a handler that
# looks up `deps.llm_svc` at call time. A submodule that instead writes
# `from .deps import llm_svc` captures its own reference at import time, so
# the patch call succeeds (no AttributeError) but the handler keeps talking
# to the real service — a silent hole where the test still passes.
# ---------------------------------------------------------------------------

class TestDepsAreReachedByAttribute:
    def test_submodules_never_value_import_the_singletons(self):
        from pathlib import Path

        package_dir = Path(__file__).resolve().parent.parent / 'bot' / 'handlers' / 'journal'
        for path in package_dir.glob('*.py'):
            if path.name == 'deps.py':
                continue  # deps.py's own docstring names the anti-pattern by example
            src = path.read_text()
            assert 'from .deps import' not in src, path
            assert 'from bot.handlers.journal.deps import' not in src, path


# ---------------------------------------------------------------------------
# Phase 4 — content-triggered crisis detection
#
# The mood threshold only ever saw the number. These cover the case it always
# missed: an unremarkable rating attached to alarming text.
# ---------------------------------------------------------------------------

class TestContentTriggeredCrisis:
    def _sent(self, update) -> list:
        return [c.args[0] for c in update.message.reply_text.call_args_list]

    async def _run(self, mood_score: int, text: str) -> tuple:
        ctx = _context({'name': 'Alice', 'mood_score': mood_score})
        update = _update(text)
        with patch('bot.handlers.journal.deps.journal_svc') as mock_svc, \
             patch('bot.handlers.journal.deps.llm_svc') as mock_llm:
            mock_svc.get_stats.return_value = {'streak': 1, 'total': 1, 'avg_mood': mood_score}
            mock_llm.extract_tags.return_value = []
            mock_llm.get_empathetic_response.return_value = 'Hang in there.'
            result = await handle_entry_text(update, ctx)
        return result, update, ctx

    async def test_high_mood_with_crisis_text_receives_resources(self):
        _, update, _ = await self._run(8, 'Good day overall but I still want to kill myself')
        assert GUIDANCE_CRISIS_RESOURCES in self._sent(update)

    async def test_mid_mood_with_crisis_text_receives_resources(self):
        _, update, _ = await self._run(6, "I can't go on like this")
        assert GUIDANCE_CRISIS_RESOURCES in self._sent(update)

    async def test_high_mood_with_ordinary_text_does_not(self):
        _, update, _ = await self._run(8, 'Work was busy but fine')
        assert GUIDANCE_CRISIS_RESOURCES not in self._sent(update)

    async def test_resources_come_before_anything_that_can_fail(self):
        _, update, _ = await self._run(9, 'I want to die')
        assert self._sent(update)[0] == GUIDANCE_CRISIS_RESOURCES

    async def test_shown_once_when_both_triggers_fire(self):
        """A low rating *and* matching text is one situation, not two messages."""
        _, update, _ = await self._run(1, 'I want to kill myself')
        assert self._sent(update).count(GUIDANCE_CRISIS_RESOURCES) == 1

    async def test_crisis_text_opens_the_guidance_offer_at_any_rating(self):
        result, _, _ = await self._run(9, 'I want to die')
        assert result == CHECK_IN_GUIDANCE_OFFER

    async def test_crisis_text_marks_the_check_in_acute(self):
        """Drives the grounding technique set rather than behavioural activation."""
        _, _, ctx = await self._run(9, 'I want to die')
        assert ctx.user_data['acute'] is True

    async def test_a_low_rating_alone_is_not_acute(self):
        _, _, ctx = await self._run(4, 'Rough day at work')
        assert ctx.user_data['acute'] is False

    async def test_the_entry_is_still_saved(self):
        """Detection changes what is shown, never whether the entry is kept."""
        ctx = _context({'name': 'Alice', 'mood_score': 9})
        with patch('bot.handlers.journal.deps.journal_svc') as mock_svc, \
             patch('bot.handlers.journal.deps.llm_svc') as mock_llm:
            mock_svc.get_stats.return_value = {'streak': 1, 'total': 1, 'avg_mood': 9}
            mock_llm.extract_tags.return_value = []
            mock_llm.get_empathetic_response.return_value = 'ok'
            await handle_entry_text(_update('I want to die'), ctx)
        mock_svc.save_entry.assert_called_once()

    async def test_detection_never_calls_the_llm(self):
        """The gate is deterministic — an Anthropic outage must not open it."""
        with patch('bot.handlers.journal.deps.llm_svc') as mock_llm:
            mock_llm.extract_tags.side_effect = Exception('Anthropic down')
            update = _update('I want to kill myself')
            with patch('bot.handlers.journal.deps.journal_svc'):
                await handle_entry_text(update, _context({'name': 'A', 'mood_score': 7}))
        assert GUIDANCE_CRISIS_RESOURCES in self._sent(update)


# ---------------------------------------------------------------------------
# Phase 4 — cohort capture
#
# Neither field can be reconstructed later, which is why they ship now.
# ---------------------------------------------------------------------------

class TestAcquisitionSource:
    async def _start_with(self, args, existing=None) -> MagicMock:
        ctx = _context()
        ctx.args = args
        with patch('bot.handlers.journal.deps.user_svc') as mock_svc:
            mock_svc.get.return_value = existing
            await start(_update('/start'), ctx)
        return mock_svc

    async def test_a_deep_link_payload_is_recorded(self):
        mock_svc = await self._start_with(['reddit'])
        assert mock_svc.create_or_update.call_args.kwargs == {'acquisition_source': 'reddit'}

    async def test_no_payload_is_recorded_as_direct(self):
        mock_svc = await self._start_with([])
        assert mock_svc.create_or_update.call_args.kwargs == {'acquisition_source': 'direct'}

    async def test_the_payload_is_lowercased(self):
        mock_svc = await self._start_with(['Reddit'])
        assert mock_svc.create_or_update.call_args.kwargs == {'acquisition_source': 'reddit'}

    async def test_a_payload_that_is_not_a_plain_slug_is_discarded(self):
        """The payload is part of a URL anyone can craft, so it is untrusted."""
        mock_svc = await self._start_with(['<script>alert(1)</script>'])
        assert mock_svc.create_or_update.call_args.kwargs == {'acquisition_source': 'direct'}

    async def test_an_over_long_payload_is_discarded(self):
        mock_svc = await self._start_with(['x' * 64])
        assert mock_svc.create_or_update.call_args.kwargs == {'acquisition_source': 'direct'}

    async def test_first_touch_wins(self):
        """A returning pre-onboarding user keeps the source that first brought them."""
        mock_svc = await self._start_with(['twitter'], existing={'acquisition_source': 'reddit'})
        mock_svc.create_or_update.assert_not_called()

    async def test_an_onboarded_user_is_not_re_attributed(self):
        mock_svc = await self._start_with(['twitter'], existing={'name': 'A', 'onboarded': True})
        mock_svc.create_or_update.assert_not_called()


class TestTherapyCohortQuestion:
    async def _answer(self, text: str) -> MagicMock:
        with patch('bot.handlers.journal.deps.user_svc') as mock_svc:
            mock_svc.get.return_value = {
                'name': 'Alice', 'timezone': 'Europe/London', 'reminder_time': '09:00'
            }
            state = await handle_therapy(_update(text), _context({'name': 'Alice'}))
        return mock_svc, state

    async def test_yes_is_recorded(self):
        mock_svc, _ = await self._answer('Yes')
        assert mock_svc.create_or_update.call_args.kwargs == {'in_therapy': 'yes'}

    async def test_no_is_recorded(self):
        mock_svc, _ = await self._answer('No')
        assert mock_svc.create_or_update.call_args.kwargs == {'in_therapy': 'no'}

    async def test_declining_to_answer_is_its_own_value(self):
        """Distinct from never having been asked — a different cohort."""
        mock_svc, _ = await self._answer('Prefer not to say')
        assert mock_svc.create_or_update.call_args.kwargs == {'in_therapy': 'undisclosed'}

    async def test_unrecognised_text_is_treated_as_undisclosed(self):
        mock_svc, _ = await self._answer('why do you ask')
        assert mock_svc.create_or_update.call_args.kwargs == {'in_therapy': 'undisclosed'}

    async def test_any_answer_completes_onboarding(self):
        """The question is optional and last; it must never trap anyone."""
        for text in ('Yes', 'No', 'Prefer not to say', 'something else entirely'):
            _, state = await self._answer(text)
            assert state == MAIN_MENU

    async def test_the_closing_message_is_built_from_the_stored_account(self):
        """`timezone` and `reminder_time` are not on the persistence allowlist,
        so the confirmation is read back rather than trusted to user_data."""
        update = _update('Yes')
        with patch('bot.handlers.journal.deps.user_svc') as mock_svc:
            mock_svc.get.return_value = {
                'name': 'Alice', 'timezone': 'Europe/London', 'reminder_time': '21:30'
            }
            await handle_therapy(update, _context())
        assert '21:30' in update.message.reply_text.call_args.args[0]

    async def _closing_message(self, answer: str, timezone: str = 'Europe/London') -> str:
        update = _update(answer)
        with patch('bot.handlers.journal.deps.user_svc') as mock_svc:
            mock_svc.get.return_value = {'name': 'Alice', 'timezone': timezone, 'reminder_time': '09:00'}
            await handle_therapy(update, _context())
        return update.message.reply_text.call_args.args[0]

    async def test_someone_in_therapy_is_told_how_to_use_the_export(self):
        from messages.strings import ONBOARDING_THERAPY_TIP
        assert ONBOARDING_THERAPY_TIP in await self._closing_message('Yes')

    async def test_everyone_else_gets_the_plain_closing_message(self):
        from messages.strings import ONBOARDING_THERAPY_TIP
        for answer in ('No', 'Prefer not to say', 'why do you ask'):
            assert ONBOARDING_THERAPY_TIP not in await self._closing_message(answer)

    async def test_the_closing_message_explains_check_ins_notes_flag_and_export(self):
        text = await self._closing_message('No')
        for phrase in ('*daily check-in*', '*note*', '*/flag*', '*/export*'):
            assert phrase in text

    async def test_an_underscore_in_the_timezone_is_escaped(self):
        """The message is sent as Markdown; a bare underscore in America/New_York
        opens an italic span Telegram cannot close, and the send is rejected."""
        assert 'America/New\\_York' in await self._closing_message('No', timezone='America/New_York')


# ---------------------------------------------------------------------------
# Phase 4 — LLM spend ceiling
#
# Every surface degrades rather than refusing. The thing the user wrote is
# never what gets dropped.
# ---------------------------------------------------------------------------

def _exhausted():
    """A budget that refuses every reservation."""
    return patch('bot.handlers.journal.deps.usage_svc.consume_llm', return_value=False)


class TestCheckInAtTheCeiling:
    async def _run(self, text: str = 'A quiet day') -> tuple:
        ctx = _context({'name': 'Alice', 'mood_score': 6})
        update = _update(text)
        with _exhausted(), \
             patch('bot.handlers.journal.deps.journal_svc') as mock_svc, \
             patch('bot.handlers.journal.deps.llm_svc') as mock_llm:
            mock_svc.get_stats.return_value = {'streak': 4, 'total': 9, 'avg_mood': 6}
            result = await handle_entry_text(update, ctx)
        return result, update, mock_svc, mock_llm

    async def test_the_entry_is_still_saved(self):
        _, _, mock_svc, _ = await self._run()
        mock_svc.save_entry.assert_called_once()

    async def test_no_anthropic_call_is_made(self):
        _, _, _, mock_llm = await self._run()
        mock_llm.extract_tags.assert_not_called()
        mock_llm.get_empathetic_response.assert_not_called()

    async def test_the_entry_is_saved_without_tags(self):
        _, _, mock_svc, _ = await self._run()
        assert mock_svc.save_entry.call_args.args[3] == []

    async def test_the_user_is_told_rather_than_left_wondering(self):
        _, update, _, _ = await self._run()
        assert 'limit' in update.message.reply_text.call_args.args[0]

    async def test_the_streak_is_still_reported(self):
        _, update, _, _ = await self._run()
        assert '4 day(s)' in update.message.reply_text.call_args.args[0]

    async def test_the_conversation_still_ends_on_the_main_menu(self):
        result, _, _, _ = await self._run()
        assert result == MAIN_MENU

    async def test_crisis_resources_are_unaffected(self):
        """The safety path costs nothing, so a budget cannot close it."""
        ctx = _context({'name': 'Alice', 'mood_score': 1})
        update = _update('I want to die')
        with _exhausted(), \
             patch('bot.handlers.journal.deps.journal_svc') as mock_svc, \
             patch('bot.handlers.journal.deps.llm_svc'):
            mock_svc.get_stats.return_value = {'streak': 1, 'total': 1, 'avg_mood': 1}
            await handle_entry_text(update, ctx)
        sent = [c.args[0] for c in update.message.reply_text.call_args_list]
        assert GUIDANCE_CRISIS_RESOURCES in sent


class TestGuidanceAtTheCeiling:
    async def _run(self) -> MagicMock:
        from bot.keyboards import GUIDANCE_YES
        ctx = _context({'name': 'Alice', 'mood_score': 2, 'entry_text': 'awful', 'acute': True})
        update = _update(GUIDANCE_YES)
        with _exhausted(), patch('bot.handlers.journal.deps.llm_svc') as mock_llm:
            await handle_guidance_offer(update, ctx)
            self.mock_llm = mock_llm
        return update

    async def test_a_real_exercise_is_sent_not_an_apology(self):
        """This user just asked for help; "try again later" is the wrong answer."""
        from messages.strings import GUIDANCE_STATIC_FALLBACK
        update = await self._run()
        assert update.message.reply_text.call_args.args[0] == GUIDANCE_STATIC_FALLBACK

    async def test_no_anthropic_call_is_made(self):
        await self._run()
        self.mock_llm.get_psychological_guidance.assert_not_called()


class TestWeeklySummaryAtTheCeiling:
    async def _run(self) -> MagicMock:
        _set_user_timezone('Europe/London')
        update = _update('')
        entries = [
            {'created_at': datetime(2026, 3, 24, 9, 0), 'mood_score': 5, 'text': 'a', 'tags': ['work']},
            {'created_at': datetime(2026, 3, 25, 9, 0), 'mood_score': 6, 'text': 'b', 'tags': ['work']},
            {'created_at': datetime(2026, 3, 26, 9, 0), 'mood_score': 7, 'text': 'c', 'tags': []},
        ]
        with _exhausted(), \
             patch('bot.handlers.journal.deps.journal_svc') as mock_svc, \
             patch('bot.handlers.journal.deps.llm_svc') as mock_llm:
            mock_svc.get_weekly_entries.return_value = entries
            await show_weekly_summary(update, _context())
            self.mock_llm = mock_llm
        return update

    async def test_the_trend_still_renders(self):
        """Everything above the LLM paragraph is computed locally and free."""
        update = await self._run()
        assert '7/10' in update.message.reply_text.call_args.args[0].replace('*', '')

    async def test_the_tags_still_render(self):
        update = await self._run()
        assert '#work' in update.message.reply_text.call_args.args[0]

    async def test_the_pattern_paragraph_is_replaced_with_an_explanation(self):
        update = await self._run()
        assert 'paused until tomorrow' in update.message.reply_text.call_args.args[0]

    async def test_no_anthropic_call_is_made(self):
        await self._run()
        self.mock_llm.get_weekly_summary.assert_not_called()


# ---------------------------------------------------------------------------
# Phase 4 — instrumentation
#
# Asserted at the boundary: the events must reach the analytics service with
# the props that make them answerable, and never with the entry text.
# ---------------------------------------------------------------------------

class TestInstrumentation:
    @staticmethod
    def _tracked(mock_analytics) -> dict:
        """Every recorded event, keyed by name, with its props."""
        return {c.args[0]: c.kwargs for c in mock_analytics.track.call_args_list}

    async def test_a_completed_check_in_is_recorded(self):
        ctx = _context({'name': 'Alice', 'mood_score': 6})
        with patch('bot.handlers.journal.deps.analytics_svc') as analytics, \
             patch('bot.handlers.journal.deps.journal_svc') as mock_svc, \
             patch('bot.handlers.journal.deps.llm_svc') as mock_llm:
            mock_svc.get_stats.return_value = {'streak': 3, 'total': 5, 'avg_mood': 6}
            mock_llm.extract_tags.return_value = ['work']
            mock_llm.get_empathetic_response.return_value = 'ok'
            await handle_entry_text(_update('A long-ish day at the office'), ctx)
        props = self._tracked(analytics)['check_in_completed']
        assert props['mood_score'] == 6
        assert props['streak'] == 3
        assert props['tag_count'] == 1
        assert props['llm'] is True

    async def test_a_check_in_event_carries_a_length_not_the_text(self):
        """The single most important property of this event stream."""
        entry = 'Something private that must not be copied into a second store'
        ctx = _context({'name': 'Alice', 'mood_score': 6})
        with patch('bot.handlers.journal.deps.analytics_svc') as analytics, \
             patch('bot.handlers.journal.deps.journal_svc') as mock_svc, \
             patch('bot.handlers.journal.deps.llm_svc') as mock_llm:
            mock_svc.get_stats.return_value = {'streak': 1, 'total': 1, 'avg_mood': 6}
            mock_llm.extract_tags.return_value = []
            mock_llm.get_empathetic_response.return_value = 'ok'
            await handle_entry_text(_update(entry), ctx)
        props = self._tracked(analytics)['check_in_completed']
        assert props['text_length'] == len(entry)
        assert entry not in str(props)

    async def test_a_failed_check_in_is_recorded(self):
        ctx = _context({'name': 'Alice', 'mood_score': 6})
        with patch('bot.handlers.journal.deps.analytics_svc') as analytics, \
             patch('bot.handlers.journal.deps.journal_svc') as mock_svc, \
             patch('bot.handlers.journal.deps.llm_svc'):
            mock_svc.save_entry.side_effect = Exception('DB down')
            await handle_entry_text(_update('a day'), ctx)
        assert 'check_in_failed' in self._tracked(analytics)

    async def test_crisis_delivery_records_its_trigger_and_categories(self):
        """The only way the lexicon's false-positive rate ever becomes knowable."""
        ctx = _context({'name': 'Alice', 'mood_score': 8})
        with patch('bot.handlers.journal.deps.analytics_svc') as analytics, \
             patch('bot.handlers.journal.deps.journal_svc') as mock_svc, \
             patch('bot.handlers.journal.deps.llm_svc') as mock_llm:
            mock_svc.get_stats.return_value = {'streak': 1, 'total': 1, 'avg_mood': 8}
            mock_llm.extract_tags.return_value = []
            mock_llm.get_empathetic_response.return_value = 'ok'
            await handle_entry_text(_update('I want to kill myself'), ctx)
        props = self._tracked(analytics)['crisis_resources_shown']
        assert props['triggers'] == ['content']
        assert props['categories'] == ['suicidal_intent']

    async def test_both_triggers_are_distinguishable(self):
        ctx = _context({'name': 'Alice', 'mood_score': 1})
        with patch('bot.handlers.journal.deps.analytics_svc') as analytics, \
             patch('bot.handlers.journal.deps.journal_svc') as mock_svc, \
             patch('bot.handlers.journal.deps.llm_svc') as mock_llm:
            mock_svc.get_stats.return_value = {'streak': 1, 'total': 1, 'avg_mood': 1}
            mock_llm.extract_tags.return_value = []
            mock_llm.get_empathetic_response.return_value = 'ok'
            await handle_entry_text(_update('I want to die'), ctx)
        assert self._tracked(analytics)['crisis_resources_shown']['triggers'] == ['mood', 'content']

    async def test_guidance_uptake_is_recorded(self):
        from bot.keyboards import GUIDANCE_YES
        ctx = _context({'name': 'Alice', 'mood_score': 2, 'entry_text': 'x'})
        with patch('bot.handlers.journal.deps.analytics_svc') as analytics, \
             patch('bot.handlers.journal.deps.llm_svc'):
            await handle_guidance_offer(_update(GUIDANCE_YES), ctx)
        assert 'guidance_accepted' in self._tracked(analytics)

    async def test_declining_guidance_is_recorded(self):
        ctx = _context({'name': 'Alice', 'mood_score': 2, 'entry_text': 'x'})
        with patch('bot.handlers.journal.deps.analytics_svc') as analytics:
            await handle_guidance_offer(_update('No thanks'), ctx)
        assert 'guidance_declined' in self._tracked(analytics)

    async def test_onboarding_start_records_the_source(self):
        ctx = _context()
        ctx.args = ['reddit']
        with patch('bot.handlers.journal.deps.analytics_svc') as analytics, \
             patch('bot.handlers.journal.deps.user_svc') as mock_svc:
            mock_svc.get.return_value = None
            await start(_update('/start'), ctx)
        assert self._tracked(analytics)['onboarding_started']['source'] == 'reddit'

    async def test_onboarding_completion_is_recorded(self):
        ctx = _context({'name': 'Alice', 'timezone': 'Europe/London'})
        with patch('bot.handlers.journal.deps.analytics_svc') as analytics, \
             patch('bot.handlers.journal.deps.user_svc'):
            await handle_reminder_time(_update('09:00'), ctx)
        assert 'onboarding_completed' in self._tracked(analytics)

    async def test_the_cohort_answer_is_recorded(self):
        with patch('bot.handlers.journal.deps.analytics_svc') as analytics, \
             patch('bot.handlers.journal.deps.user_svc') as mock_svc:
            mock_svc.get.return_value = {'name': 'A', 'timezone': 'UTC', 'reminder_time': '09:00'}
            await handle_therapy(_update('Yes'), _context())
        assert self._tracked(analytics)['cohort_recorded']['in_therapy'] == 'yes'

    async def test_hitting_the_ceiling_is_recorded_with_its_surface(self):
        ctx = _context({'name': 'Alice', 'mood_score': 6})
        with _exhausted(), \
             patch('bot.handlers.journal.deps.analytics_svc') as analytics, \
             patch('bot.handlers.journal.deps.journal_svc') as mock_svc, \
             patch('bot.handlers.journal.deps.llm_svc'):
            mock_svc.get_stats.return_value = {'streak': 1, 'total': 1, 'avg_mood': 6}
            await handle_entry_text(_update('a day'), ctx)
        assert self._tracked(analytics)['llm_budget_exceeded']['surface'] == 'check_in'

    async def test_read_surfaces_are_recorded(self):
        _set_user_timezone('Europe/London')
        with patch('bot.handlers.journal.deps.analytics_svc') as analytics, \
             patch('bot.handlers.journal.deps.journal_svc') as mock_svc:
            mock_svc.get_recent_entries.return_value = [
                {'created_at': datetime(2026, 3, 26, 9, 0), 'mood_score': 5, 'text': 'a', 'tags': []}
            ]
            mock_svc.get_stats.return_value = {'streak': 1, 'total': 1, 'avg_mood': 5}
            await show_history(_update(''), _context())
            await show_stats(_update(''), _context())
        tracked = self._tracked(analytics)
        assert 'history_viewed' in tracked
        assert 'stats_viewed' in tracked

    async def test_an_empty_read_surface_is_still_recorded(self):
        """Someone who opens their history and finds nothing is the most
        interesting reader of it — and the easiest one to never record."""
        _set_user_timezone('Europe/London')
        with patch('bot.handlers.journal.deps.analytics_svc') as analytics, \
             patch('bot.handlers.journal.deps.journal_svc') as mock_svc:
            mock_svc.get_recent_entries.return_value = []
            mock_svc.get_stats.return_value = {'streak': 0, 'total': 0, 'avg_mood': 0}
            mock_svc.get_weekly_entries.return_value = []
            await show_history(_update(''), _context())
            await show_stats(_update(''), _context())
            await show_weekly_summary(_update(''), _context())
        tracked = self._tracked(analytics)
        assert tracked['history_viewed']['count'] == 0
        assert tracked['stats_viewed']['total'] == 0
        assert tracked['weekly_summary_viewed']['entry_count'] == 0


# ---------------------------------------------------------------------------
# Metering outages
# ---------------------------------------------------------------------------

def _metering_down():
    """A usage repository that cannot be reached.

    Patched at the repository rather than at `consume_llm`, so the real
    `UsageService` sits in the path and these tests prove the whole chain
    degrades — not just that the handlers cope with a `False` someone handed
    them.
    """
    return patch(
        'repositories.usage_repo.UsageRepository.increment',
        side_effect=RuntimeError('mongo is down'),
    )


class TestCheckInWhenMeteringIsDown:
    async def _run(self, text: str = 'A quiet day') -> tuple:
        ctx = _context({'name': 'Alice', 'mood_score': 6})
        update = _update(text)
        with _metering_down(), \
             patch('bot.handlers.journal.deps.journal_svc') as mock_svc, \
             patch('bot.handlers.journal.deps.llm_svc') as mock_llm:
            mock_svc.get_stats.return_value = {'streak': 4, 'total': 9, 'avg_mood': 6}
            result = await handle_entry_text(update, ctx)
        return result, update, mock_svc, mock_llm

    async def test_the_entry_is_still_saved(self):
        """The failure is in the meter, not in the thing the user came to do."""
        _, _, mock_svc, _ = await self._run()
        mock_svc.save_entry.assert_called_once()

    async def test_no_anthropic_call_is_made(self):
        """Fail closed on spend: unmetered calls are not made."""
        _, _, _, mock_llm = await self._run()
        mock_llm.extract_tags.assert_not_called()
        mock_llm.get_empathetic_response.assert_not_called()

    async def test_the_user_reaches_the_main_menu(self):
        result, _, _, _ = await self._run()
        assert result == MAIN_MENU

    async def test_crisis_resources_still_reach_a_user_who_needs_them(self):
        """Nothing about a broken counter may stand between this text and the numbers."""
        ctx = _context({'name': 'Alice', 'mood_score': 6})
        update = _update('I want to die')
        with _metering_down(), \
             patch('bot.handlers.journal.deps.journal_svc') as mock_svc, \
             patch('bot.handlers.journal.deps.llm_svc'):
            mock_svc.get_stats.return_value = {'streak': 1, 'total': 1, 'avg_mood': 6}
            await handle_entry_text(update, ctx)
        assert GUIDANCE_CRISIS_RESOURCES in [c.args[0] for c in update.message.reply_text.call_args_list]


class TestGuidanceWhenMeteringIsDown:
    async def test_a_real_exercise_is_sent_not_an_apology(self):
        """This user tapped "yes, help me". A metering outage is not their problem."""
        from bot.keyboards import GUIDANCE_YES
        from messages.strings import GUIDANCE_STATIC_FALLBACK
        ctx = _context({'name': 'Alice', 'mood_score': 2, 'entry_text': 'awful', 'acute': True})
        update = _update(GUIDANCE_YES)
        with _metering_down(), patch('bot.handlers.journal.deps.llm_svc'):
            await handle_guidance_offer(update, ctx)
        assert update.message.reply_text.call_args.args[0] == GUIDANCE_STATIC_FALLBACK


class TestWeeklySummaryWhenMeteringIsDown:
    async def test_the_locally_computed_trend_still_renders(self):
        """Only the closing paragraph costs a call; the rows above it are free."""
        _set_user_timezone('Europe/London')
        update = _update('')
        entries = [
            {'created_at': datetime(2026, 3, 24, 9, 0), 'mood_score': 5, 'text': 'a', 'tags': ['work']},
            {'created_at': datetime(2026, 3, 25, 9, 0), 'mood_score': 6, 'text': 'b', 'tags': ['work']},
            {'created_at': datetime(2026, 3, 26, 9, 0), 'mood_score': 7, 'text': 'c', 'tags': []},
        ]
        with _metering_down(), \
             patch('bot.handlers.journal.deps.journal_svc') as mock_svc, \
             patch('bot.handlers.journal.deps.llm_svc'):
            mock_svc.get_weekly_entries.return_value = entries
            await show_weekly_summary(update, _context())
        body = update.message.reply_text.call_args.args[0]
        assert '#work' in body
        assert mood_bar(7) in body


class TestFailedCheckInRefundsTheUnspentCall:
    """Two calls are reserved, and the save sits between them.

    A database failure means the reply was never requested, so charging for it
    walks a user toward a ceiling on work that never reached Anthropic. The tag
    call is not refunded — by that point it has been made.
    """

    async def _run_failing_check_in(self) -> MagicMock:
        ctx = _context({'name': 'Alice', 'mood_score': 6})
        with patch('bot.handlers.journal.deps.usage_svc') as usage, \
             patch('bot.handlers.journal.deps.journal_svc') as mock_svc, \
             patch('bot.handlers.journal.deps.llm_svc'):
            usage.consume_llm.return_value = True
            mock_svc.save_entry.side_effect = RuntimeError('mongo is down')
            await handle_entry_text(_update('A quiet day'), ctx)
        return usage

    async def test_exactly_one_call_is_handed_back(self):
        usage = await self._run_failing_check_in()
        usage.refund.assert_called_once()
        assert usage.refund.call_args.args[1] == 1

    async def test_nothing_is_refunded_when_nothing_was_reserved(self):
        """A user already at the ceiling spent nothing, so there is nothing to return."""
        ctx = _context({'name': 'Alice', 'mood_score': 6})
        with patch('bot.handlers.journal.deps.usage_svc') as usage, \
             patch('bot.handlers.journal.deps.journal_svc') as mock_svc, \
             patch('bot.handlers.journal.deps.llm_svc'):
            usage.consume_llm.return_value = False
            mock_svc.save_entry.side_effect = RuntimeError('mongo is down')
            await handle_entry_text(_update('A quiet day'), ctx)
        usage.refund.assert_not_called()

    async def test_a_successful_check_in_refunds_nothing(self):
        ctx = _context({'name': 'Alice', 'mood_score': 6})
        with patch('bot.handlers.journal.deps.usage_svc') as usage, \
             patch('bot.handlers.journal.deps.journal_svc') as mock_svc, \
             patch('bot.handlers.journal.deps.llm_svc') as mock_llm:
            usage.consume_llm.return_value = True
            mock_llm.extract_tags.return_value = ['work']
            mock_llm.get_empathetic_response.return_value = 'That sounds hard.'
            mock_svc.get_stats.return_value = {'streak': 1, 'total': 1, 'avg_mood': 6}
            await handle_entry_text(_update('A quiet day'), ctx)
        usage.refund.assert_not_called()


# ---------------------------------------------------------------------------
# Phase 5 — /export
# ---------------------------------------------------------------------------

class TestSendExport:
    @staticmethod
    def _export(count: int = 3):
        from services.export import Export
        return Export(filename='journal-2026-09-30.md', content=b'# Journal', entry_count=count, flagged_count=0)

    async def test_the_file_is_sent_as_a_document(self):
        from bot.handlers.journal import send_export
        update = _update('/export')
        with patch('bot.handlers.journal.deps.export_svc') as export_svc, \
             patch('bot.handlers.journal.deps.analytics_svc'):
            export_svc.build.return_value = self._export()
            state = await send_export(update, _context())
        assert state == MAIN_MENU
        kwargs = update.message.reply_document.call_args.kwargs
        assert kwargs['document'] == b'# Journal'
        assert kwargs['filename'] == 'journal-2026-09-30.md'
        assert '3 entries' in kwargs['caption']
        assert len(kwargs['caption']) <= 1024

    async def test_nothing_to_export_says_so_and_sends_no_file(self):
        from bot.handlers.journal import send_export
        update = _update('/export')
        with patch('bot.handlers.journal.deps.export_svc') as export_svc, \
             patch('bot.handlers.journal.deps.analytics_svc'):
            export_svc.build.return_value = None
            state = await send_export(update, _context())
        assert state == MAIN_MENU
        update.message.reply_document.assert_not_called()
        assert 'nothing to export' in update.message.reply_text.call_args.args[0]

    async def test_a_failure_returns_to_the_menu_with_an_apology(self):
        from bot.handlers.journal import send_export
        from messages.strings import ERROR_GENERIC
        update = _update('/export')
        with patch('bot.handlers.journal.deps.export_svc') as export_svc:
            export_svc.build.side_effect = Exception('DB down')
            state = await send_export(update, _context())
        assert state == MAIN_MENU
        assert update.message.reply_text.call_args.args[0] == ERROR_GENERIC

    async def test_the_request_is_recorded_including_empty_ones(self):
        from bot.handlers.journal import send_export
        with patch('bot.handlers.journal.deps.export_svc') as export_svc, \
             patch('bot.handlers.journal.deps.analytics_svc') as analytics:
            export_svc.build.return_value = None
            await send_export(_update('/export'), _context())
        event, _ = analytics.track.call_args.args
        assert event == 'export_requested'
        assert analytics.track.call_args.kwargs == {'entry_count': 0, 'flagged_count': 0, 'days': 30}

    async def test_the_menu_button_exports(self):
        from bot.handlers.journal import handle_main_menu
        from bot.keyboards import EXPORT
        update = _update(EXPORT)
        with patch('bot.handlers.journal.deps.export_svc') as export_svc, \
             patch('bot.handlers.journal.deps.analytics_svc'):
            export_svc.build.return_value = self._export()
            await handle_main_menu(update, _context({'name': 'Sam'}))
        assert update.message.reply_document.called

    async def test_a_stale_export_button_works_after_state_loss(self):
        from bot.keyboards import EXPORT
        update = _update(EXPORT)
        with patch('bot.handlers.journal.deps.user_svc') as user_svc, \
             patch('bot.handlers.journal.deps.export_svc') as export_svc, \
             patch('bot.handlers.journal.deps.analytics_svc'):
            user_svc.get.return_value = {'telegram_id': 12345, 'name': 'Sam', 'onboarded': True}
            export_svc.build.return_value = self._export()
            await recover_state(update, _context())
        assert update.message.reply_document.called


# ---------------------------------------------------------------------------
# Phase 5 — /delete
#
# The fan-out is tested against a real (mongomock) database in
# tests/test_account_service.py. These cover the conversation around it: that
# nothing is deleted without the exact confirmation, and that the in-memory
# state the database cannot see is cleared too.
# ---------------------------------------------------------------------------

class TestDelete:
    async def test_delete_asks_before_doing_anything(self):
        from bot.handlers.journal import DELETE_CONFIRM, request_delete
        from messages.strings import DELETE_CONFIRM_PROMPT
        update = _update('/delete')
        with patch('bot.handlers.journal.deps.account_svc') as account_svc:
            state = await request_delete(update, _context())
        assert state == DELETE_CONFIRM
        assert update.message.reply_text.call_args.args[0] == DELETE_CONFIRM_PROMPT
        account_svc.delete_everything.assert_not_called()

    def test_the_prompt_is_honest_about_what_it_cannot_reach(self):
        from messages.strings import DELETE_CONFIRM_PROMPT
        assert 'Telegram chat' in DELETE_CONFIRM_PROMPT
        assert 'Anthropic' in DELETE_CONFIRM_PROMPT
        assert '/export' in DELETE_CONFIRM_PROMPT

    async def test_the_confirm_button_deletes_everything(self):
        from telegram import ReplyKeyboardRemove
        from telegram.ext import ConversationHandler
        from bot.handlers.journal import handle_delete_confirmation
        from bot.keyboards import DELETE_YES
        from messages.strings import DELETE_DONE
        update = _update(DELETE_YES)
        ctx = _context({'name': 'Sam', 'mood_score': 3})
        with patch('bot.handlers.journal.deps.account_svc') as account_svc, \
             patch('bot.handlers.journal.deps.analytics_svc'):
            account_svc.delete_everything.return_value = {'entries': 4}
            state = await handle_delete_confirmation(update, ctx)
        account_svc.delete_everything.assert_called_once_with(12345)
        assert state == ConversationHandler.END
        assert update.message.reply_text.call_args.args[0] == DELETE_DONE
        assert isinstance(update.message.reply_text.call_args.kwargs['reply_markup'], ReplyKeyboardRemove)

    async def test_in_memory_user_data_is_cleared_so_persistence_cannot_restore_it(self):
        from bot.handlers.journal import handle_delete_confirmation
        from bot.keyboards import DELETE_YES
        ctx = _context({'name': 'Sam', 'mood_score': 3})
        with patch('bot.handlers.journal.deps.account_svc') as account_svc, \
             patch('bot.handlers.journal.deps.analytics_svc'):
            account_svc.delete_everything.return_value = {}
            await handle_delete_confirmation(_update(DELETE_YES), ctx)
        assert ctx.user_data == {}
        ctx.application.drop_user_data.assert_called_once_with(12345)

    async def test_the_deletion_event_is_not_linked_to_the_user(self):
        from bot.handlers.journal import handle_delete_confirmation
        from bot.keyboards import DELETE_YES
        with patch('bot.handlers.journal.deps.account_svc') as account_svc, \
             patch('bot.handlers.journal.deps.analytics_svc') as analytics:
            account_svc.delete_everything.return_value = {'entries': 4}
            await handle_delete_confirmation(_update(DELETE_YES), _context())
        event, telegram_id = analytics.track.call_args.args
        assert event == 'account_deleted'
        assert telegram_id is None
        assert analytics.track.call_args.kwargs == {'entry_count': 4}

    @pytest.mark.parametrize('reply', ['No, keep my journal', 'yes', 'Yes, delete everything', 'delete'])
    async def test_anything_but_the_exact_button_deletes_nothing(self, reply):
        from bot.handlers.journal import handle_delete_confirmation
        from messages.strings import DELETE_CANCELLED
        update = _update(reply)
        with patch('bot.handlers.journal.deps.account_svc') as account_svc, \
             patch('bot.handlers.journal.deps.analytics_svc'), \
             patch('bot.handlers.journal.deps.user_svc') as user_svc:
            user_svc.get.return_value = {'name': 'Sam', 'onboarded': True}
            state = await handle_delete_confirmation(update, _context())
        account_svc.delete_everything.assert_not_called()
        assert state == MAIN_MENU
        assert update.message.reply_text.call_args.args[0] == DELETE_CANCELLED

    async def test_cancelling_mid_onboarding_does_not_offer_a_menu(self):
        from telegram.ext import ConversationHandler
        from bot.handlers.journal import handle_delete_confirmation
        with patch('bot.handlers.journal.deps.account_svc'), \
             patch('bot.handlers.journal.deps.analytics_svc'), \
             patch('bot.handlers.journal.deps.user_svc') as user_svc:
            user_svc.get.return_value = {'acquisition_source': 'direct'}
            state = await handle_delete_confirmation(_update('no'), _context())
        assert state == ConversationHandler.END

    async def test_a_failed_deletion_says_so_and_can_be_retried(self):
        from telegram.ext import ConversationHandler
        from bot.handlers.journal import handle_delete_confirmation
        from bot.keyboards import DELETE_YES
        from messages.strings import DELETE_FAILED
        from services.account_service import DeletionIncomplete
        update = _update(DELETE_YES)
        with patch('bot.handlers.journal.deps.account_svc') as account_svc, \
             patch('bot.handlers.journal.deps.analytics_svc') as analytics:
            account_svc.delete_everything.side_effect = DeletionIncomplete(['entries'])
            state = await handle_delete_confirmation(update, _context())
        assert state == ConversationHandler.END
        assert update.message.reply_text.call_args.args[0] == DELETE_FAILED
        assert '/delete' in DELETE_FAILED
        analytics.track.assert_not_called()

    def test_privacy_notice_and_help_describe_it(self):
        from messages.strings import HELP_MESSAGE, PRIVACY_NOTICE
        assert '/delete' in PRIVACY_NOTICE
        assert '/delete' in HELP_MESSAGE
        assert 'no self-serve delete' not in PRIVACY_NOTICE.lower()


# ---------------------------------------------------------------------------
# Phase 5 — /flag, marking an entry to raise in session
# ---------------------------------------------------------------------------

class TestToggleFlag:
    async def _flag(self, entry):
        from bot.handlers.journal import toggle_flag
        update = _update('/flag')
        with patch('bot.handlers.journal.deps.journal_svc') as journal_svc, \
             patch('bot.handlers.journal.deps.user_svc') as user_svc, \
             patch('bot.handlers.journal.deps.analytics_svc') as analytics:
            journal_svc.toggle_session_flag.return_value = entry
            user_svc.get.return_value = {'timezone': 'Pacific/Kiritimati'}
            state = await toggle_flag(update, _context())
        return state, update.message.reply_text.call_args.args[0], analytics

    async def test_flagging_confirms_which_entry_in_local_time(self):
        # 11:00 UTC on Thu 26 Mar is already Fri 27 Mar in Kiritimati (UTC+14).
        state, text, _ = await self._flag({'created_at': datetime(2026, 3, 26, 11, 0), 'flagged_for_session': True})
        assert state == MAIN_MENU
        assert 'Flagged your entry from Fri 27 Mar' in text

    async def test_unflagging_says_so(self):
        _, text, _ = await self._flag({'created_at': datetime(2026, 3, 26, 11, 0), 'flagged_for_session': False})
        assert text.startswith('Removed the flag')

    async def test_no_entries_yet(self):
        from messages.strings import FLAG_NO_ENTRY
        state, text, analytics = await self._flag(None)
        assert state == MAIN_MENU
        assert text == FLAG_NO_ENTRY
        analytics.track.assert_not_called()

    async def test_the_toggle_is_recorded_without_content(self):
        _, _, analytics = await self._flag({'created_at': datetime(2026, 3, 26, 11, 0), 'flagged_for_session': True})
        assert analytics.track.call_args.args[0] == 'session_flag_toggled'
        assert analytics.track.call_args.kwargs == {'flagged': True}

    def test_the_check_in_reply_points_at_it(self):
        from messages.strings import CHECK_IN_DONE, CHECK_IN_DONE_BRIEF
        assert '/flag' in CHECK_IN_DONE
        assert '/flag' in CHECK_IN_DONE_BRIEF


# ---------------------------------------------------------------------------
# Phase 6 — the daily check-in and later notes
#
# The first entry of the local day is the check-in; any later one is a note.
# Notes are never refused — only the reply and the streak line are dropped —
# so everything that protects a user still runs on them.
# ---------------------------------------------------------------------------

class TestNotes:
    @staticmethod
    def _tracked(mock_analytics) -> dict:
        return {c.args[0]: c.kwargs for c in mock_analytics.track.call_args_list}

    async def _run(self, mood_score: int = 6, text: str = 'Something came up', first_of_day: bool = False):
        ctx = _context({'name': 'Alice', 'mood_score': mood_score})
        update = _update(text)
        with patch('bot.handlers.journal.deps.usage_svc') as usage, \
             patch('bot.handlers.journal.deps.analytics_svc') as analytics, \
             patch('bot.handlers.journal.deps.journal_svc') as mock_svc, \
             patch('bot.handlers.journal.deps.llm_svc') as mock_llm:
            usage.consume_llm.return_value = True
            mock_svc.save_entry.return_value = first_of_day
            mock_svc.get_stats.return_value = {'streak': 3, 'total': 5, 'avg_mood': mood_score}
            mock_llm.extract_tags.return_value = ['work']
            mock_llm.get_empathetic_response.return_value = 'A reflection.'
            state = await handle_entry_text(update, ctx)
        sent = [c.args[0] for c in update.message.reply_text.call_args_list]
        return state, sent, usage, analytics, mock_svc, mock_llm

    async def test_a_note_is_saved_with_its_tags(self):
        _, _, _, _, mock_svc, _ = await self._run()
        assert mock_svc.save_entry.call_args.args[3] == ['work']

    async def test_a_note_gets_no_reflection(self):
        _, sent, _, _, _, mock_llm = await self._run()
        mock_llm.get_empathetic_response.assert_not_called()
        assert 'A reflection.' not in sent[-1]

    async def test_a_note_is_acknowledged_without_a_streak_line(self):
        from messages.strings import NOTE_SAVED
        _, sent, _, _, _, _ = await self._run()
        assert sent[-1] == NOTE_SAVED.format(name='Alice')
        assert 'in a row' not in sent[-1]

    async def test_a_note_hands_back_the_reply_call(self):
        """Both calls are reserved before the save; only the tag call was spent."""
        _, _, usage, _, _, _ = await self._run()
        usage.refund.assert_called_once()
        assert usage.refund.call_args.args[1] == 1

    async def test_a_note_at_the_ceiling_refunds_nothing(self):
        ctx = _context({'name': 'Alice', 'mood_score': 6})
        with patch('bot.handlers.journal.deps.usage_svc') as usage, \
             patch('bot.handlers.journal.deps.journal_svc') as mock_svc, \
             patch('bot.handlers.journal.deps.llm_svc'):
            usage.consume_llm.return_value = False
            mock_svc.save_entry.return_value = False
            mock_svc.get_stats.return_value = {'streak': 3, 'total': 5, 'avg_mood': 6}
            await handle_entry_text(_update('x'), ctx)
        usage.refund.assert_not_called()

    async def test_the_daily_check_in_still_gets_its_reflection(self):
        _, sent, usage, _, _, mock_llm = await self._run(first_of_day=True)
        mock_llm.get_empathetic_response.assert_called_once()
        assert 'A reflection.' in sent[-1]
        usage.refund.assert_not_called()

    async def test_crisis_resources_fire_on_a_note(self):
        _, sent, _, _, _, _ = await self._run(mood_score=7, text='I want to die')
        assert GUIDANCE_CRISIS_RESOURCES in sent

    async def test_a_low_mood_note_still_offers_guidance(self):
        state, _, _, _, _, _ = await self._run(mood_score=3)
        assert state == CHECK_IN_GUIDANCE_OFFER

    async def test_the_event_says_which_kind(self):
        _, _, _, note_analytics, _, _ = await self._run()
        _, _, _, daily_analytics, _, _ = await self._run(first_of_day=True)
        assert self._tracked(note_analytics)['check_in_completed']['kind'] == 'note'
        assert self._tracked(daily_analytics)['check_in_completed']['kind'] == 'daily'

    async def test_second_entry_of_the_day_is_a_note_end_to_end(self):
        """Through the real JournalService: the streak store decides, not a mock."""
        from messages.strings import NOTE_SAVED
        replies = []
        with patch('bot.handlers.journal.deps.llm_svc') as mock_llm:
            mock_llm.extract_tags.return_value = []
            mock_llm.get_empathetic_response.return_value = 'A reflection.'
            for text in ('morning', 'afternoon'):
                update = _update(text)
                await handle_entry_text(update, _context({'name': 'Alice', 'mood_score': 6}))
                replies.append(update.message.reply_text.call_args.args[0])
        assert 'A reflection.' in replies[0]
        assert replies[1] == NOTE_SAVED.format(name='Alice')
        assert mock_llm.get_empathetic_response.call_count == 1


class TestCheckInPromptAfterCheckingIn:
    async def _prompt(self, checked_in, label: str = '📝 Check In') -> str:
        from bot.handlers.journal import handle_main_menu
        update = _update(label)
        with patch('bot.handlers.journal.deps.journal_svc') as mock_svc:
            if isinstance(checked_in, Exception):
                mock_svc.checked_in_today.side_effect = checked_in
            else:
                mock_svc.checked_in_today.return_value = checked_in
            state = await handle_main_menu(update, _context({'name': 'Sam'}))
        assert state == CHECK_IN_MOOD
        return update.message.reply_text.call_args.args[0]

    async def test_first_of_the_day_asks_for_the_check_in(self):
        from messages.strings import CHECK_IN_MOOD_PROMPT
        assert await self._prompt(False) == CHECK_IN_MOOD_PROMPT.format(name='Sam')

    async def test_later_in_the_day_offers_a_note(self):
        from messages.strings import NOTE_MOOD_PROMPT
        assert await self._prompt(True) == NOTE_MOOD_PROMPT.format(name='Sam')

    async def test_a_stale_add_a_note_label_still_starts_the_days_check_in(self):
        """The keyboard does not change at midnight. The prompt goes by the day, not the label."""
        from bot.keyboards import ADD_NOTE
        from messages.strings import CHECK_IN_MOOD_PROMPT
        assert await self._prompt(False, label=ADD_NOTE) == CHECK_IN_MOOD_PROMPT.format(name='Sam')

    async def test_a_failed_read_still_starts_an_entry(self):
        """The read only picks the wording, so it must not cost the user their tap."""
        from messages.strings import CHECK_IN_MOOD_PROMPT
        assert await self._prompt(RuntimeError('mongo down')) == CHECK_IN_MOOD_PROMPT.format(name='Sam')


def _entry_button(reply_markup) -> str:
    """The label on the first row of a main-menu keyboard."""
    return reply_markup.keyboard[0][0].text


class TestMenuButtonLabel:
    async def _stats_button(self, **journal_svc) -> str:
        update = _update('')
        with patch('bot.handlers.journal.deps.journal_svc') as mock_svc, \
             patch('bot.handlers.journal.deps.user_svc'), \
             patch('bot.handlers.journal.deps.analytics_svc'):
            mock_svc.get_stats.return_value = {'streak': 0, 'total': 0, 'avg_mood': None}
            mock_svc.configure_mock(**journal_svc)
            await show_stats(update, _context({'name': 'Sam'}))
        return _entry_button(update.message.reply_text.call_args.kwargs['reply_markup'])

    async def test_check_in_before_todays_check_in(self):
        from bot.keyboards import CHECK_IN
        assert await self._stats_button(**{'checked_in_today.return_value': False}) == CHECK_IN

    async def test_add_a_note_after_todays_check_in(self):
        from bot.keyboards import ADD_NOTE
        assert await self._stats_button(**{'checked_in_today.return_value': True}) == ADD_NOTE

    async def test_a_failed_read_falls_back_to_check_in(self):
        from bot.keyboards import CHECK_IN
        assert await self._stats_button(**{'checked_in_today.side_effect': RuntimeError('mongo down')}) == CHECK_IN

    @pytest.mark.parametrize('first_of_day', [True, False])
    async def test_a_completed_entry_returns_add_a_note(self, first_of_day):
        from bot.keyboards import ADD_NOTE
        update = _update('A quiet day')
        with patch('bot.handlers.journal.deps.usage_svc') as usage, \
             patch('bot.handlers.journal.deps.analytics_svc'), \
             patch('bot.handlers.journal.deps.journal_svc') as mock_svc, \
             patch('bot.handlers.journal.deps.llm_svc') as mock_llm:
            usage.consume_llm.return_value = True
            mock_svc.save_entry.return_value = first_of_day
            mock_svc.get_stats.return_value = {'streak': 1, 'total': 1, 'avg_mood': 7}
            mock_llm.extract_tags.return_value = []
            mock_llm.get_empathetic_response.return_value = 'A reflection.'
            await handle_entry_text(update, _context({'name': 'Alice', 'mood_score': 7}))
        mock_svc.checked_in_today.assert_not_called()
        assert _entry_button(update.message.reply_text.call_args.kwargs['reply_markup']) == ADD_NOTE
