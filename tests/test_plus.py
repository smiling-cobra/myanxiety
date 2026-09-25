"""Plus: who has it, what it unlocks, and where it may be offered.

The plan is one field, `plus_until`, read through `services/plan_service.py`.
The handler tests patch `deps.plan_svc.is_plus`, which is the only thing any
gate asks; the plan service itself runs against the mongomock database.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import pytest

from bot.handlers.journal import (
    MAIN_MENU,
    handle_entry_text,
    handle_guidance_offer,
    handle_settings_choice,
    send_export,
    show_plus,
)
from bot.keyboards import GUIDANCE_NO, GUIDANCE_YES, PLUS, get_settings_keyboard
from messages import strings
from repositories.user_repo import UserRepository
from services.export import EXPORT_DAYS, PLUS_EXPORT_DAYS, Export
from services.payment_service import PLUS_PAYLOAD, PLUS_PRICE_STARS
from services.plan_service import (
    SOURCE_ADMIN,
    SOURCE_LAUNCH_TRIAL,
    SOURCE_SUBSCRIPTION,
    PlanService,
    is_plus,
)
from tests.conftest import make_context as _context, make_update as _update

USER_ID = 12345
NOW = datetime(2026, 9, 24, 10, 0, tzinfo=timezone.utc)


def _save_user(**fields) -> None:
    UserRepository().save({
        'telegram_id': USER_ID, 'name': 'Sam', 'timezone': 'Europe/London',
        'reminder_time': '09:00', 'onboarded': True, **fields,
    })


def _stored() -> dict:
    return UserRepository().find(USER_ID)


def _at(now: datetime = NOW):
    return patch('services.time_utils.now', return_value=now)


def _plan(plus: bool):
    return patch('bot.handlers.journal.deps.plan_svc.is_plus', return_value=plus)


def _tracked(analytics) -> dict:
    return {c.args[0]: c.kwargs for c in analytics.track.call_args_list}


# ---------------------------------------------------------------------------
# Entitlement
# ---------------------------------------------------------------------------

class TestIsPlus:
    def test_no_field_is_free(self):
        assert is_plus({'telegram_id': 1}, NOW) is False

    def test_no_user_is_free(self):
        assert is_plus(None, NOW) is False

    def test_a_future_end_is_plus(self):
        assert is_plus({'plus_until': NOW + timedelta(seconds=1)}, NOW) is True

    def test_it_ends_exactly_at_plus_until(self):
        assert is_plus({'plus_until': NOW}, NOW) is False

    def test_a_naive_stored_datetime_is_read_as_utc(self):
        """pymongo hands back naive datetimes; they are UTC, not local time."""
        assert is_plus({'plus_until': (NOW + timedelta(minutes=1)).replace(tzinfo=None)}, NOW) is True

    def test_a_malformed_value_is_free(self):
        assert is_plus({'plus_until': '2099-01-01'}, NOW) is False


class TestPlanService:
    def test_reads_the_stored_plan(self):
        _save_user(plus_until=NOW + timedelta(days=3))
        with _at():
            assert PlanService().is_plus(USER_ID) is True

    def test_a_failed_read_answers_free_and_does_not_raise(self):
        svc = PlanService()
        with patch.object(svc._users, 'find', side_effect=Exception('mongo down')):
            assert svc.is_plus(USER_ID) is False

    def test_extend_moves_the_end_forward(self):
        _save_user(plus_until=NOW + timedelta(days=3), plus_source=SOURCE_LAUNCH_TRIAL)
        with _at():
            PlanService().extend(USER_ID, NOW + timedelta(days=30), SOURCE_SUBSCRIPTION)
        stored = _stored()
        assert stored['plus_until'].replace(tzinfo=timezone.utc) == NOW + timedelta(days=30)
        assert stored['plus_source'] == SOURCE_SUBSCRIPTION

    def test_extend_never_shortens(self):
        _save_user(plus_until=NOW + timedelta(days=60), plus_source=SOURCE_ADMIN)
        with _at():
            PlanService().extend(USER_ID, NOW + timedelta(days=30), SOURCE_SUBSCRIPTION)
        stored = _stored()
        assert stored['plus_until'].replace(tzinfo=timezone.utc) == NOW + timedelta(days=60)
        assert stored['plus_source'] == SOURCE_ADMIN

    def test_extend_does_not_recreate_a_deleted_account(self):
        with _at():
            PlanService().extend(USER_ID, NOW + timedelta(days=30), SOURCE_SUBSCRIPTION)
        assert _stored() is None


# ---------------------------------------------------------------------------
# Perk 1: a written reply to every note
# ---------------------------------------------------------------------------

class TestNoteReplies:
    async def _run(self, plus: bool, first_of_day: bool = False, mood_score: int = 6, text: str = 'Later on'):
        ctx = _context({'name': 'Alice', 'mood_score': mood_score})
        update = _update(text)
        with _plan(plus), \
             patch('bot.handlers.journal.deps.usage_svc') as usage, \
             patch('bot.handlers.journal.deps.analytics_svc') as analytics, \
             patch('bot.handlers.journal.deps.journal_svc') as journal, \
             patch('bot.handlers.journal.deps.llm_svc') as llm:
            usage.consume_llm.return_value = True
            journal.save_entry.return_value = first_of_day
            journal.get_stats.return_value = {'streak': 3, 'total': 5, 'avg_mood': mood_score}
            llm.extract_tags.return_value = []
            llm.get_empathetic_response.return_value = 'A reflection.'
            state = await handle_entry_text(update, ctx)
        sent = [c.args[0] for c in update.message.reply_text.call_args_list]
        return state, sent, usage, analytics, llm

    async def test_a_plus_note_gets_a_reply(self):
        _, sent, _, _, llm = await self._run(plus=True)
        llm.get_empathetic_response.assert_called_once()
        assert sent[-1] == strings.NOTE_REPLY.format(name='Alice', llm_response='A reflection.')

    async def test_a_plus_note_has_no_streak_line(self):
        _, sent, _, _, _ = await self._run(plus=True)
        assert 'in a row' not in sent[-1]

    async def test_a_plus_note_keeps_its_reply_call(self):
        _, _, usage, _, _ = await self._run(plus=True)
        usage.refund.assert_not_called()

    async def test_a_free_note_is_unchanged(self):
        _, sent, usage, _, llm = await self._run(plus=False)
        llm.get_empathetic_response.assert_not_called()
        assert sent[-1] == strings.NOTE_SAVED.format(name='Alice')
        usage.refund.assert_called_once()

    async def test_the_daily_check_in_is_the_same_on_both_plans(self):
        _, free, _, _, _ = await self._run(plus=False, first_of_day=True)
        _, plus, _, _, _ = await self._run(plus=True, first_of_day=True)
        assert free[-1] == plus[-1]
        assert 'A reflection.' in free[-1]

    async def test_a_plus_note_at_the_ceiling_is_acknowledged(self):
        ctx = _context({'name': 'Alice', 'mood_score': 6})
        update = _update('x')
        with _plan(True), \
             patch('bot.handlers.journal.deps.usage_svc') as usage, \
             patch('bot.handlers.journal.deps.journal_svc') as journal, \
             patch('bot.handlers.journal.deps.llm_svc') as llm:
            usage.consume_llm.return_value = False
            journal.save_entry.return_value = False
            journal.get_stats.return_value = {'streak': 3, 'total': 5, 'avg_mood': 6}
            await handle_entry_text(update, ctx)
        llm.get_empathetic_response.assert_not_called()
        assert update.message.reply_text.call_args.args[0] == strings.NOTE_SAVED.format(name='Alice')

    async def test_the_event_records_the_plan(self):
        _, _, _, analytics, _ = await self._run(plus=True)
        assert _tracked(analytics)['check_in_completed']['plus'] is True


# ---------------------------------------------------------------------------
# The upsell rule: never in the entry flow
# ---------------------------------------------------------------------------

def _mentions_plus(text: str) -> bool:
    return '/plus' in text or 'Plus' in text


class TestNoOfferInTheEntryFlow:
    """Someone who has just written about a hard moment never meets a sales pitch."""

    @pytest.mark.parametrize('plus', [True, False])
    @pytest.mark.parametrize('first_of_day', [True, False])
    @pytest.mark.parametrize('llm_allowed', [True, False])
    @pytest.mark.parametrize('mood_score, text', [(8, 'fine'), (3, 'rough'), (1, 'awful'), (7, 'I want to die')])
    async def test_no_check_in_reply_mentions_plus(self, plus, first_of_day, llm_allowed, mood_score, text):
        ctx = _context({'name': 'Alice', 'mood_score': mood_score})
        update = _update(text)
        with _plan(plus), \
             patch('bot.handlers.journal.deps.usage_svc') as usage, \
             patch('bot.handlers.journal.deps.analytics_svc'), \
             patch('bot.handlers.journal.deps.journal_svc') as journal, \
             patch('bot.handlers.journal.deps.llm_svc') as llm:
            usage.consume_llm.return_value = llm_allowed
            journal.save_entry.return_value = first_of_day
            journal.get_stats.return_value = {'streak': 1, 'total': 1, 'avg_mood': mood_score}
            llm.extract_tags.return_value = []
            llm.get_empathetic_response.return_value = 'A reflection.'
            await handle_entry_text(update, ctx)
        for call in update.message.reply_text.call_args_list:
            assert not _mentions_plus(call.args[0])

    @pytest.mark.parametrize('answer', [GUIDANCE_YES, GUIDANCE_NO])
    @pytest.mark.parametrize('llm_allowed', [True, False])
    async def test_no_guidance_reply_mentions_plus(self, answer, llm_allowed):
        ctx = _context({'name': 'Alice', 'mood_score': 2, 'entry_text': 'rough', 'acute': True})
        update = _update(answer)
        with _plan(False), \
             patch('bot.handlers.journal.deps.usage_svc') as usage, \
             patch('bot.handlers.journal.deps.analytics_svc'), \
             patch('bot.handlers.journal.deps.llm_svc') as llm:
            usage.consume_llm.return_value = llm_allowed
            llm.get_psychological_guidance.return_value = 'Try this.'
            await handle_guidance_offer(update, ctx)
        for call in update.message.reply_text.call_args_list:
            assert not _mentions_plus(call.args[0])

    @pytest.mark.parametrize('name', [
        'REMINDER_MESSAGE', 'GUIDANCE_CRISIS_RESOURCES', 'GUIDANCE_STATIC_FALLBACK', 'GUIDANCE_OFFER_LOW',
        'GUIDANCE_OFFER_VERY_LOW', 'CHECK_IN_DONE', 'CHECK_IN_DONE_BRIEF', 'NOTE_SAVED', 'NOTE_REPLY',
    ])
    def test_no_entry_flow_template_mentions_plus(self, name):
        assert not _mentions_plus(getattr(strings, name))


# ---------------------------------------------------------------------------
# Perk 3: the longer export window
# ---------------------------------------------------------------------------

class TestExportWindow:
    @staticmethod
    def _export():
        return Export(filename='journal.md', content=b'# Journal', entry_count=2, flagged_count=0)

    async def _run(self, plus: bool):
        update = _update('/export')
        with _plan(plus), \
             patch('bot.handlers.journal.deps.export_svc') as export_svc, \
             patch('bot.handlers.journal.deps.analytics_svc') as analytics:
            export_svc.build.return_value = self._export()
            state = await send_export(update, _context())
        return state, update, export_svc, analytics

    async def test_free_exports_the_last_30_days(self):
        state, update, export_svc, _ = await self._run(plus=False)
        assert state == MAIN_MENU
        assert export_svc.build.call_args.args == (USER_ID, EXPORT_DAYS)
        assert '30 days' in update.message.reply_document.call_args.kwargs['caption']

    async def test_plus_exports_the_last_90_days(self):
        _, update, export_svc, _ = await self._run(plus=True)
        assert export_svc.build.call_args.args == (USER_ID, PLUS_EXPORT_DAYS)
        assert '90 days' in update.message.reply_document.call_args.kwargs['caption']

    async def test_only_the_free_caption_mentions_plus(self):
        _, free, _, analytics = await self._run(plus=False)
        _, plus, _, _ = await self._run(plus=True)
        assert '/plus' in free.message.reply_document.call_args.kwargs['caption']
        assert '/plus' not in plus.message.reply_document.call_args.kwargs['caption']
        assert _tracked(analytics)['paywall_shown'] == {'surface': 'export'}

    async def test_the_caption_stays_under_telegrams_limit(self):
        _, update, _, _ = await self._run(plus=False)
        assert len(update.message.reply_document.call_args.kwargs['caption']) <= 1024


# ---------------------------------------------------------------------------
# /plus
# ---------------------------------------------------------------------------

def _plus_context():
    ctx = _context()
    ctx.bot_data = {}
    ctx.bot.create_invoice_link = AsyncMock(return_value='https://t.me/$invoice')
    return ctx


def _inline_button(update):
    markup = update.message.reply_text.call_args_list[0].kwargs['reply_markup']
    return markup.inline_keyboard[0][0]


class TestShowPlus:
    async def test_a_free_user_sees_the_offer_and_a_subscribe_button(self):
        _save_user()
        update, ctx = _update('/plus'), _plus_context()
        with _at():
            state = await show_plus(update, ctx)
        assert state == MAIN_MENU
        assert '250 Stars' in update.message.reply_text.call_args_list[0].args[0]
        assert _inline_button(update).url == 'https://t.me/$invoice'

    async def test_the_invoice_link_is_a_stars_subscription(self):
        _save_user()
        ctx = _plus_context()
        with _at():
            await show_plus(_update('/plus'), ctx)
        kwargs = ctx.bot.create_invoice_link.call_args.kwargs
        assert kwargs['currency'] == 'XTR'
        assert kwargs['payload'] == PLUS_PAYLOAD
        assert kwargs['prices'][0].amount == PLUS_PRICE_STARS
        assert kwargs['subscription_period'] == 30 * 24 * 60 * 60
        assert 'provider_token' not in kwargs

    async def test_the_link_is_created_once(self):
        _save_user()
        ctx = _plus_context()
        with _at():
            await show_plus(_update('/plus'), ctx)
            await show_plus(_update('/plus'), ctx)
        assert ctx.bot.create_invoice_link.await_count == 1

    async def test_a_trial_user_sees_when_it_ends(self):
        _save_user(plus_until=NOW + timedelta(days=10), plus_source=SOURCE_LAUNCH_TRIAL)
        update = _update('/plus')
        with _at(), patch('bot.handlers.journal.deps.analytics_svc') as analytics:
            await show_plus(update, _plus_context())
        assert '4 October 2026' in update.message.reply_text.call_args_list[0].args[0]
        assert _tracked(analytics)['plus_viewed'] == {'status': 'trial'}

    async def test_a_subscriber_sees_their_period_and_how_to_cancel(self):
        _save_user(plus_until=NOW + timedelta(days=20), plus_source=SOURCE_SUBSCRIPTION)
        update, ctx = _update('/plus'), _plus_context()
        with _at():
            await show_plus(update, ctx)
        text = update.message.reply_text.call_args_list[0].args[0]
        assert '14 October 2026' in text
        assert 'My Stars' in text
        ctx.bot.create_invoice_link.assert_not_called()

    async def test_not_available_before_the_account_exists(self):
        UserRepository().save({'telegram_id': USER_ID})
        update = _update('/plus')
        with _at():
            state = await show_plus(update, _plus_context())
        assert state is None

    async def test_the_settings_menu_has_a_plus_button(self):
        buttons = [b.text for row in get_settings_keyboard(paused=False).keyboard for b in row]
        assert PLUS in buttons

    async def test_the_settings_button_opens_plus(self):
        _save_user()
        update = _update(PLUS)
        with _at():
            state = await handle_settings_choice(update, _plus_context())
        assert state == MAIN_MENU
        assert '250 Stars' in update.message.reply_text.call_args_list[0].args[0]

    def test_the_copy_makes_no_treatment_claims(self):
        for text in (strings.PLUS_OFFER, strings.PLUS_WELCOME, strings.PLUS_ACTIVE):
            lowered = text.lower()
            for word in ('treat', 'cure', 'therapy', 'anxiety relief', 'heal'):
                assert word not in lowered

    def test_the_offer_guarantees_the_free_core(self):
        for word in ('crisis', '30-day export', '/delete', 'reminders'):
            assert word in strings.PLUS_OFFER
