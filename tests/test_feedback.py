"""/feedback, and the one-time ask after `FEEDBACK_ASK_AFTER` entries.

The feedback service and the user record run against the mongomock database;
analytics, the LLM and the journal are patched where a check-in is driven.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import pytest

from bot.handlers.journal import (
    FEEDBACK_TEXT,
    MAIN_MENU,
    handle_entry_text,
    handle_feedback_text,
    handle_settings_choice,
    request_feedback,
)
from bot.handlers.journal.checkin import FEEDBACK_ASKED
from bot.handlers.journal.states import FEEDBACK_ASK_AFTER
from bot.keyboards import BACK, SEND_FEEDBACK
from db.db import feedback_collection
from messages import strings
from repositories.user_repo import UserRepository
from services.feedback_service import DAILY_FEEDBACK_LIMIT, MAX_FEEDBACK_LENGTH, FeedbackService
from tests.conftest import make_context as _context, make_update as _update

USER_ID = 12345
NOW = datetime(2026, 10, 10, 10, 0, tzinfo=timezone.utc)


def _save_user(**fields) -> None:
    UserRepository().save({
        'telegram_id': USER_ID, 'name': 'Sam', 'timezone': 'Europe/London',
        'reminder_time': '09:00', 'onboarded': True, **fields,
    })


def _at(now: datetime = NOW):
    return patch('services.time_utils.now', return_value=now)


def _stored() -> list[dict]:
    return list(feedback_collection().find({'telegram_id': USER_ID}, {'_id': 0}))


def _sent(update) -> list[str]:
    return [c.args[0] for c in update.message.reply_text.call_args_list]


def _tracked(analytics) -> dict:
    return {c.args[0]: c.kwargs for c in analytics.track.call_args_list}


def _feedback_context(user_data: dict | None = None):
    ctx = _context(user_data)
    ctx.bot.send_message = AsyncMock()
    return ctx


# ---------------------------------------------------------------------------
# Storage and the daily cap
# ---------------------------------------------------------------------------

class TestFeedbackService:
    def test_a_message_is_stored_with_its_user_and_plan(self):
        _save_user()
        with _at():
            assert FeedbackService().submit(USER_ID, 'Dark mode please') is True
        [row] = _stored()
        assert row['text'] == 'Dark mode please'
        assert row['is_plus'] is False
        assert row['created_at'].replace(tzinfo=timezone.utc) == NOW

    def test_the_cap_refuses_the_message_after_the_limit(self):
        _save_user()
        svc = FeedbackService()
        with _at():
            for i in range(DAILY_FEEDBACK_LIMIT):
                assert svc.submit(USER_ID, f'idea {i}')
            assert svc.submit(USER_ID, 'one too many') is False
            assert svc.can_submit(USER_ID) is False
        assert len(_stored()) == DAILY_FEEDBACK_LIMIT

    def test_the_cap_resets_at_local_midnight(self):
        # 23:30 in Tokyo is 14:30 UTC; local midnight comes before the UTC one.
        _save_user(timezone='Asia/Tokyo')
        svc = FeedbackService()
        evening = datetime(2026, 10, 10, 14, 30, tzinfo=timezone.utc)
        with _at(evening):
            for i in range(DAILY_FEEDBACK_LIMIT):
                svc.submit(USER_ID, f'idea {i}')
            assert svc.can_submit(USER_ID) is False
        with _at(evening + timedelta(hours=1)):
            assert svc.can_submit(USER_ID) is True

    def test_other_users_do_not_count_toward_the_cap(self):
        svc = FeedbackService()
        with _at():
            for i in range(DAILY_FEEDBACK_LIMIT):
                svc.submit(999, f'idea {i}')
            assert svc.can_submit(USER_ID) is True


# ---------------------------------------------------------------------------
# /feedback and the Settings button
# ---------------------------------------------------------------------------

class TestRequestFeedback:
    async def test_it_asks_for_one_message(self):
        _save_user()
        update, ctx = _update('/feedback'), _feedback_context()
        assert await request_feedback(update, ctx) == FEEDBACK_TEXT
        assert _sent(update) == [strings.FEEDBACK_PROMPT.format(limit=MAX_FEEDBACK_LENGTH)]
        assert ctx.user_data['feedback_source'] == 'command'

    async def test_before_onboarding_it_leaves_the_step_alone(self):
        update = _update('/feedback')
        assert await request_feedback(update, _feedback_context()) is None
        assert _sent(update) == [strings.FEEDBACK_NOT_READY]

    async def test_at_the_cap_it_does_not_ask(self):
        _save_user()
        with _at():
            for i in range(DAILY_FEEDBACK_LIMIT):
                FeedbackService().submit(USER_ID, f'idea {i}')
            update = _update('/feedback')
            assert await request_feedback(update, _feedback_context()) == MAIN_MENU
        assert _sent(update) == [strings.FEEDBACK_LIMIT_REACHED]

    async def test_after_the_ask_it_counts_as_the_prompt(self):
        _save_user()
        ctx = _feedback_context({FEEDBACK_ASKED: True})
        await request_feedback(_update('/feedback'), ctx)
        assert ctx.user_data['feedback_source'] == 'prompt'
        assert FEEDBACK_ASKED not in ctx.user_data

    async def test_the_settings_button_opens_it(self):
        _save_user()
        update, ctx = _update(SEND_FEEDBACK), _feedback_context()
        with patch('bot.handlers.journal.deps.analytics_svc'):
            assert await handle_settings_choice(update, ctx) == FEEDBACK_TEXT
        assert ctx.user_data['feedback_source'] == 'settings'


class TestHandleFeedbackText:
    async def _send(self, text: str, admins=frozenset({1, 2}), user_data=None, send_error=None):
        _save_user()
        update = _update(text)
        ctx = _feedback_context(user_data if user_data is not None else {'feedback_source': 'settings'})
        if send_error:
            ctx.bot.send_message.side_effect = send_error
        with _at(), \
             patch('bot.handlers.journal.feedback.admin_ids', return_value=admins), \
             patch('bot.handlers.journal.deps.analytics_svc') as analytics:
            state = await handle_feedback_text(update, ctx)
        return state, update, ctx, analytics

    async def test_it_is_stored_acknowledged_and_returns_to_the_menu(self):
        state, update, _, _ = await self._send('  Dark mode please  ')
        assert state == MAIN_MENU
        assert [row['text'] for row in _stored()] == ['Dark mode please']
        assert _sent(update) == [strings.FEEDBACK_THANKS]

    async def test_every_admin_gets_a_plain_text_copy(self):
        _, _, ctx, _ = await self._send('Use *bold* _here_')
        assert {c.kwargs['chat_id'] for c in ctx.bot.send_message.call_args_list} == {1, 2}
        for call in ctx.bot.send_message.call_args_list:
            assert 'parse_mode' not in call.kwargs
            assert call.kwargs['text'] == strings.FEEDBACK_ADMIN_FORWARD.format(
                telegram_id=USER_ID, source='settings', plan='free', text='Use *bold* _here_'
            )

    async def test_a_failed_forward_still_saves_and_thanks(self):
        state, update, _, _ = await self._send('An idea', send_error=RuntimeError('blocked'))
        assert state == MAIN_MENU
        assert len(_stored()) == 1
        assert _sent(update) == [strings.FEEDBACK_THANKS]

    async def test_no_admins_still_saves(self):
        _, update, ctx, _ = await self._send('An idea', admins=frozenset())
        assert len(_stored()) == 1
        ctx.bot.send_message.assert_not_called()

    async def test_the_event_carries_the_length_and_source_never_the_text(self):
        _, _, _, analytics = await self._send('An idea')
        assert _tracked(analytics)['feedback_sent'] == {'text_length': 7, 'source': 'settings'}

    async def test_a_lost_source_is_recorded_as_the_command(self):
        _, _, _, analytics = await self._send('An idea', user_data={})
        assert _tracked(analytics)['feedback_sent']['source'] == 'command'

    async def test_a_crisis_match_sends_resources_first_and_still_saves(self):
        _, update, _, analytics = await self._send('honestly I want to die')
        sent = _sent(update)
        assert sent[0] == strings.GUIDANCE_CRISIS_RESOURCES
        assert sent[-1] == strings.FEEDBACK_THANKS
        assert len(_stored()) == 1
        assert _tracked(analytics)['crisis_resources_shown']['triggers'] == ['content']

    async def test_too_long_asks_again_and_stores_nothing(self):
        text = 'x' * (MAX_FEEDBACK_LENGTH + 1)
        state, update, _, _ = await self._send(text)
        assert state == FEEDBACK_TEXT
        assert _stored() == []
        assert _sent(update) == [strings.FEEDBACK_TOO_LONG.format(limit=MAX_FEEDBACK_LENGTH, length=len(text))]

    async def test_back_stores_nothing(self):
        state, _, ctx, _ = await self._send(BACK)
        assert state == MAIN_MENU
        assert _stored() == []
        ctx.bot.send_message.assert_not_called()

    async def test_at_the_cap_nothing_more_is_stored_or_forwarded(self):
        _save_user()
        with _at():
            for i in range(DAILY_FEEDBACK_LIMIT):
                FeedbackService().submit(USER_ID, f'idea {i}')
        _, update, ctx, _ = await self._send('one more')
        assert len(_stored()) == DAILY_FEEDBACK_LIMIT
        assert _sent(update) == [strings.FEEDBACK_LIMIT_REACHED]
        ctx.bot.send_message.assert_not_called()


# ---------------------------------------------------------------------------
# The one-time ask after FEEDBACK_ASK_AFTER entries
# ---------------------------------------------------------------------------

class TestFeedbackAsk:
    async def _check_in(
        self, mood_score: int = 7, text: str = 'a good day', first_of_day: bool = True,
        total: int = FEEDBACK_ASK_AFTER, ctx=None,
    ):
        ctx = ctx or _context({'name': 'Sam', 'mood_score': mood_score})
        ctx.user_data['mood_score'] = mood_score
        update = _update(text)
        with _at(), \
             patch('bot.handlers.journal.deps.plan_svc.is_plus', return_value=False), \
             patch('bot.handlers.journal.deps.usage_svc') as usage, \
             patch('bot.handlers.journal.deps.analytics_svc') as analytics, \
             patch('bot.handlers.journal.deps.journal_svc') as journal, \
             patch('bot.handlers.journal.deps.llm_svc') as llm:
            usage.consume_llm.return_value = True
            journal.save_entry.return_value = first_of_day
            journal.get_stats.return_value = {'streak': 3, 'total': total, 'avg_mood': mood_score}
            llm.extract_tags.return_value = []
            llm.get_empathetic_response.return_value = 'A reflection.'
            state = await handle_entry_text(update, ctx)
        return state, _sent(update), analytics, ctx

    async def test_it_follows_the_daily_check_in_that_reaches_the_threshold(self):
        _save_user()
        state, sent, analytics, ctx = await self._check_in()
        assert state == MAIN_MENU
        assert 'A reflection.' in sent[0]
        assert sent[-1] == strings.FEEDBACK_ASK
        assert UserRepository().find(USER_ID)['feedback_prompted_at'] is not None
        assert 'feedback_prompted' in _tracked(analytics)
        assert ctx.user_data[FEEDBACK_ASKED] is True

    async def test_it_is_sent_only_once(self):
        _save_user()
        await self._check_in()
        _, sent, analytics, _ = await self._check_in(total=FEEDBACK_ASK_AFTER + 1)
        assert strings.FEEDBACK_ASK not in sent
        assert 'feedback_prompted' not in _tracked(analytics)

    async def test_not_before_the_threshold(self):
        _save_user()
        _, sent, _, _ = await self._check_in(total=FEEDBACK_ASK_AFTER - 1)
        assert strings.FEEDBACK_ASK not in sent

    async def test_not_after_a_note(self):
        _save_user()
        _, sent, _, _ = await self._check_in(first_of_day=False)
        assert strings.FEEDBACK_ASK not in sent
        assert 'feedback_prompted_at' not in UserRepository().find(USER_ID)

    @pytest.mark.parametrize('mood_score', [1, 2, 3, 4])
    async def test_not_on_a_low_mood(self, mood_score):
        _save_user()
        _, sent, _, _ = await self._check_in(mood_score=mood_score)
        assert strings.FEEDBACK_ASK not in sent
        assert 'feedback_prompted_at' not in UserRepository().find(USER_ID)

    async def test_not_after_a_crisis_match(self):
        _save_user()
        _, sent, _, _ = await self._check_in(mood_score=8, text='I want to die')
        assert strings.GUIDANCE_CRISIS_RESOURCES in sent
        assert strings.FEEDBACK_ASK not in sent
        assert 'feedback_prompted_at' not in UserRepository().find(USER_ID)

    async def test_not_for_a_user_with_no_record(self):
        _, sent, _, _ = await self._check_in()
        assert strings.FEEDBACK_ASK not in sent
        assert UserRepository().find(USER_ID) is None

    async def test_a_failed_write_costs_the_ask_not_the_check_in(self):
        _save_user()
        with patch('bot.handlers.journal.deps.user_svc.update', side_effect=RuntimeError('mongo down')):
            state, sent, _, _ = await self._check_in()
        assert state == MAIN_MENU
        assert 'A reflection.' in sent[0]
        assert strings.FEEDBACK_ASK not in sent
