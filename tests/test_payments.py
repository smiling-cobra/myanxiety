"""Telegram Stars payments: checkout, the ledger, refunds, admin commands, /delete.

The services run against the mongomock database from conftest. Telegram is a
mock: `context.bot` methods are AsyncMocks, so a test can assert on the Bot API
calls the handlers make without a network.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from telegram.error import BadRequest
from telegram.ext import ConversationHandler

from bot.handlers import payments
from bot.handlers.journal import handle_delete_confirmation
from bot.keyboards import DELETE_YES
from messages import strings
from repositories.payment_repo import PaymentRepository
from repositories.user_repo import UserRepository
from services.payment_service import (
    PLUS_PAYLOAD,
    PLUS_PRICE_STARS,
    REJECT_NO_ACCOUNT,
    REJECT_UNKNOWN_PAYLOAD,
    REJECT_WRONG_AMOUNT,
    REJECT_WRONG_CURRENCY,
    PaymentService,
)
from services.plan_service import SOURCE_ADMIN, SOURCE_SUBSCRIPTION, is_plus
from tests.conftest import make_context, make_update

USER_ID = 12345
ADMIN_ID = 999
NOW = datetime(2026, 9, 24, 10, 0, tzinfo=timezone.utc)


def _save_user(telegram_id: int = USER_ID, **fields) -> None:
    UserRepository().save({'telegram_id': telegram_id, 'name': 'Sam', 'onboarded': True, **fields})


def _stored(telegram_id: int = USER_ID) -> dict:
    return UserRepository().find(telegram_id)


def _until(user: dict) -> datetime:
    return user['plus_until'].replace(tzinfo=timezone.utc)


def _at(now: datetime = NOW):
    return patch('services.time_utils.now', return_value=now)


def _record(svc: PaymentService, charge_id: str = 'c1', recurring: bool = True, first: bool = True,
            expires_at: datetime | None = NOW + timedelta(days=30)):
    return svc.record(
        USER_ID, charge_id=charge_id, provider_charge_id=None, amount=PLUS_PRICE_STARS, currency='XTR',
        payload=PLUS_PAYLOAD, is_recurring=recurring, is_first_recurring=first, expires_at=expires_at,
    )


def _bot_context(args: list[str] | None = None):
    ctx = make_context()
    ctx.args = args or []
    ctx.bot.refund_star_payment = AsyncMock(return_value=True)
    ctx.bot.edit_user_star_subscription = AsyncMock(return_value=True)
    return ctx


# ---------------------------------------------------------------------------
# PaymentService
# ---------------------------------------------------------------------------

class TestCheckout:
    @pytest.fixture
    def svc(self):
        _save_user()
        return PaymentService()

    def test_a_valid_checkout_is_approved(self, svc):
        assert svc.checkout_problem(USER_ID, PLUS_PAYLOAD, 'XTR', PLUS_PRICE_STARS) is None

    @pytest.mark.parametrize('payload, currency, amount, reason', [
        ('something_else', 'XTR', PLUS_PRICE_STARS, REJECT_UNKNOWN_PAYLOAD),
        (PLUS_PAYLOAD, 'USD', PLUS_PRICE_STARS, REJECT_WRONG_CURRENCY),
        (PLUS_PAYLOAD, 'XTR', 100, REJECT_WRONG_AMOUNT),
    ])
    def test_a_mismatched_invoice_is_refused(self, svc, payload, currency, amount, reason):
        assert svc.checkout_problem(USER_ID, payload, currency, amount) == reason

    def test_a_payer_without_an_account_is_refused(self):
        assert PaymentService().checkout_problem(4242, PLUS_PAYLOAD, 'XTR', PLUS_PRICE_STARS) == REJECT_NO_ACCOUNT

    def test_a_payer_mid_onboarding_is_refused(self):
        UserRepository().save({'telegram_id': 4242, 'name': 'New'})
        assert PaymentService().checkout_problem(4242, PLUS_PAYLOAD, 'XTR', PLUS_PRICE_STARS) == REJECT_NO_ACCOUNT


class TestRecord:
    def test_a_payment_grants_plus_until_the_paid_period_ends(self):
        _save_user()
        with _at():
            result = _record(PaymentService())
        assert result.new is True
        assert result.renewal is False
        assert _until(_stored()) == NOW + timedelta(days=30)
        assert _stored()['plus_source'] == SOURCE_SUBSCRIPTION
        with _at():
            assert is_plus(_stored())

    def test_a_redelivered_update_is_recorded_once(self):
        _save_user()
        svc = PaymentService()
        with _at():
            _record(svc)
            again = _record(svc)
        assert again.new is False
        assert PaymentRepository().find('c1') is not None
        from db.db import payments_collection
        assert payments_collection().count_documents({}) == 1

    def test_a_replayed_refunded_charge_does_not_restore_plus(self):
        _save_user()
        svc = PaymentService()
        with _at():
            _record(svc)
            svc.mark_refunded('c1')
            again = _record(svc)
            assert not is_plus(_stored())
        assert again.new is False
        assert PaymentRepository().find('c1')['refunded_at'] is not None

    def test_a_replay_repairs_a_missing_extension(self):
        """A crash between the ledger insert and the extension is fixed by a replay."""
        _save_user()
        svc = PaymentService()
        with _at():
            PaymentRepository().record({
                'telegram_id': USER_ID, 'telegram_payment_charge_id': 'c1', 'refunded_at': None,
            })
            _record(svc)
            assert is_plus(_stored())

    def test_a_payer_with_no_account_is_not_stored(self):
        with _at():
            result = _record(PaymentService())
        assert result.orphan is True
        assert PaymentRepository().find('c1') is None
        assert _stored() is None

    def test_a_renewal_extends_plus(self):
        _save_user()
        svc = PaymentService()
        with _at():
            _record(svc, 'c1')
        with _at(NOW + timedelta(days=30)):
            result = _record(svc, 'c2', first=False, expires_at=NOW + timedelta(days=60))
        assert result.renewal is True
        assert _until(_stored()) == NOW + timedelta(days=60)

    def test_a_payment_never_shortens_a_longer_grant(self):
        _save_user(plus_until=NOW + timedelta(days=90), plus_source=SOURCE_ADMIN)
        with _at():
            _record(PaymentService())
        assert _until(_stored()) == NOW + timedelta(days=90)

    def test_a_missing_expiry_falls_back_to_one_period(self):
        _save_user()
        with _at():
            _record(PaymentService(), expires_at=None)
        assert _until(_stored()) == NOW + timedelta(days=30)

    def test_the_ledger_holds_no_personal_data_beyond_ids(self):
        _save_user()
        with _at():
            _record(PaymentService())
        row = PaymentRepository().find('c1')
        assert set(row) == {
            'telegram_id', 'telegram_payment_charge_id', 'provider_payment_charge_id', 'amount', 'currency',
            'payload', 'is_recurring', 'is_first_recurring', 'expires_at', 'created_at', 'refunded_at',
        }


class TestLiveSubscription:
    def test_the_latest_unexpired_recurring_charge(self):
        _save_user()
        svc = PaymentService()
        with _at():
            _record(svc, 'c1')
        with _at(NOW + timedelta(days=30)):
            _record(svc, 'c2', first=False, expires_at=NOW + timedelta(days=60))
            assert svc.live_subscription_charge(USER_ID) == 'c2'

    def test_an_expired_subscription_cannot_renew(self):
        _save_user()
        svc = PaymentService()
        with _at():
            _record(svc)
        with _at(NOW + timedelta(days=31)):
            assert svc.live_subscription_charge(USER_ID) is None

    def test_no_payments_means_nothing_to_cancel(self):
        assert PaymentService().live_subscription_charge(USER_ID) is None

    def test_a_refunded_charge_is_not_live(self):
        _save_user()
        svc = PaymentService()
        with _at():
            _record(svc)
            svc.mark_refunded('c1')
            assert svc.live_subscription_charge(USER_ID) is None


# ---------------------------------------------------------------------------
# Handlers
# ---------------------------------------------------------------------------

def _pre_checkout_update(payload=PLUS_PAYLOAD, currency='XTR', amount=PLUS_PRICE_STARS, user_id=USER_ID):
    update = MagicMock()
    query = update.pre_checkout_query
    query.from_user.id = user_id
    query.invoice_payload = payload
    query.currency = currency
    query.total_amount = amount
    query.answer = AsyncMock()
    return update


class TestPreCheckoutHandler:
    async def test_approves_a_valid_checkout(self):
        _save_user()
        update = _pre_checkout_update()
        await payments.handle_pre_checkout(update, make_context())
        update.pre_checkout_query.answer.assert_awaited_once_with(ok=True)

    async def test_refuses_with_a_reason_and_records_it(self):
        _save_user()
        update = _pre_checkout_update(amount=1)
        with patch('bot.handlers.journal.deps.analytics_svc') as analytics:
            await payments.handle_pre_checkout(update, make_context())
        kwargs = update.pre_checkout_query.answer.call_args.kwargs
        assert kwargs['ok'] is False
        assert kwargs['error_message'] == strings.PLUS_CHECKOUT_REFUSED
        assert analytics.track.call_args.kwargs == {'reason': REJECT_WRONG_AMOUNT}

    async def test_a_payer_without_an_account_is_told_to_finish_setup(self):
        update = _pre_checkout_update(user_id=4242)
        await payments.handle_pre_checkout(update, make_context())
        assert update.pre_checkout_query.answer.call_args.kwargs['error_message'] == strings.PLUS_CHECKOUT_NO_ACCOUNT

    async def test_a_failed_check_still_answers(self):
        """An unanswered query times out the user's payment; a refusal at least says so."""
        update = _pre_checkout_update()
        with patch('bot.handlers.journal.deps.payment_svc') as svc:
            svc.checkout_problem.side_effect = Exception('mongo down')
            await payments.handle_pre_checkout(update, make_context())
        assert update.pre_checkout_query.answer.call_args.kwargs['ok'] is False


def _payment_update(charge_id='c1', recurring=True, first=True, expires=NOW + timedelta(days=30)):
    update = make_update('')
    payment = update.message.successful_payment
    payment.telegram_payment_charge_id = charge_id
    payment.provider_payment_charge_id = ''
    payment.total_amount = PLUS_PRICE_STARS
    payment.currency = 'XTR'
    payment.invoice_payload = PLUS_PAYLOAD
    payment.is_recurring = recurring
    payment.is_first_recurring = first
    payment.subscription_expiration_date = expires
    return update


class TestSuccessfulPaymentHandler:
    async def test_the_first_payment_is_welcomed_and_grants_plus(self):
        _save_user()
        update = _payment_update()
        with _at(), patch('bot.handlers.journal.deps.analytics_svc') as analytics:
            await payments.handle_successful_payment(update, make_context())
        assert '24 October 2026' in update.message.reply_text.call_args.args[0]
        assert _until(_stored()) == NOW + timedelta(days=30)
        assert analytics.track.call_args.kwargs == {'renewal': False, 'amount': PLUS_PRICE_STARS}

    async def test_a_renewal_is_silent(self):
        _save_user()
        with _at():
            await payments.handle_successful_payment(_payment_update('c1'), make_context())
            renewal = _payment_update('c2', first=False, expires=NOW + timedelta(days=60))
            await payments.handle_successful_payment(renewal, make_context())
        renewal.message.reply_text.assert_not_called()
        assert _until(_stored()) == NOW + timedelta(days=60)

    async def test_a_redelivered_payment_is_not_welcomed_twice(self):
        _save_user()
        first, again = _payment_update(), _payment_update()
        # A fresh service: the shared singleton's repository has already created
        # its unique index — on an earlier test's database.
        with _at(), patch('bot.handlers.journal.deps.payment_svc', PaymentService()):
            await payments.handle_successful_payment(first, make_context())
            await payments.handle_successful_payment(again, make_context())
        again.message.reply_text.assert_not_called()


class TestOrphanPayment:
    """A charge for an account that no longer exists is refunded, not kept."""

    async def _pay(self, ctx):
        update = _payment_update('c2', first=False, expires=NOW + timedelta(days=60))
        with _at(), patch('bot.handlers.journal.deps.analytics_svc') as analytics:
            await payments.handle_successful_payment(update, ctx)
        return update, analytics

    async def test_is_refunded_cancelled_and_not_stored(self):
        ctx = _bot_context()
        update, analytics = await self._pay(ctx)
        ctx.bot.refund_star_payment.assert_awaited_once_with(user_id=USER_ID, telegram_payment_charge_id='c2')
        ctx.bot.edit_user_star_subscription.assert_awaited_once_with(
            user_id=USER_ID, telegram_payment_charge_id='c2', is_canceled=True
        )
        update.message.reply_text.assert_not_called()
        assert PaymentRepository().find('c2') is None
        assert analytics.track.call_args.args == (payments.analytics.PLUS_ORPHAN_REFUNDED,)

    async def test_a_failed_refund_is_logged_for_a_manual_refund(self, caplog):
        ctx = _bot_context()
        ctx.bot.refund_star_payment.side_effect = BadRequest('nope')
        _, analytics = await self._pay(ctx)
        assert 'refund it by hand' in caplog.text
        assert 'c2' in caplog.text
        analytics.track.assert_not_called()


class TestRegistration:
    def test_payment_updates_are_handled_outside_the_conversation(self):
        app = MagicMock()
        payments.register(app)
        assert {c.kwargs['group'] for c in app.add_handler.call_args_list} == {-1}
        assert app.add_handler.call_count == 4


# ---------------------------------------------------------------------------
# Admin commands
# ---------------------------------------------------------------------------

@pytest.fixture
def admin(monkeypatch):
    monkeypatch.setenv('ADMIN_TELEGRAM_IDS', f'{ADMIN_ID}, 1001')
    _save_user(ADMIN_ID)


class TestAdminPlus:
    async def test_a_non_admin_gets_no_reply_and_nothing_changes(self, admin):
        _save_user()
        update = make_update('/admin_plus on', user_id=USER_ID)
        await payments.admin_plus(update, _bot_context(['on']))
        update.message.reply_text.assert_not_called()
        assert 'plus_until' not in _stored()

    async def test_no_admins_configured_means_nobody(self, monkeypatch):
        monkeypatch.delenv('ADMIN_TELEGRAM_IDS', raising=False)
        _save_user(ADMIN_ID)
        update = make_update('/admin_plus on', user_id=ADMIN_ID)
        await payments.admin_plus(update, _bot_context(['on']))
        update.message.reply_text.assert_not_called()

    async def test_on_grants_the_admin_plus(self, admin):
        with _at():
            await payments.admin_plus(make_update('', user_id=ADMIN_ID), _bot_context(['on', '7']))
            assert is_plus(_stored(ADMIN_ID))
        assert _until(_stored(ADMIN_ID)) == NOW + timedelta(days=7)
        assert _stored(ADMIN_ID)['plus_source'] == SOURCE_ADMIN

    async def test_off_ends_plus_even_a_paid_one(self, admin):
        """To test the free side from an account that has subscribed."""
        _save_user(ADMIN_ID, plus_until=NOW + timedelta(days=20), plus_source=SOURCE_SUBSCRIPTION)
        with _at():
            await payments.admin_plus(make_update('', user_id=ADMIN_ID), _bot_context(['off']))
            assert not is_plus(_stored(ADMIN_ID))

    @pytest.mark.parametrize('args', [[], ['maybe'], ['on', 'lots'], ['off', '3']])
    async def test_bad_arguments_show_usage(self, admin, args):
        update = make_update('', user_id=ADMIN_ID)
        await payments.admin_plus(update, _bot_context(args))
        assert update.message.reply_text.call_args.args[0] == strings.ADMIN_PLUS_USAGE


class TestRefund:
    async def _paid(self):
        _save_user()
        with _at():
            _record(PaymentService())

    async def test_refunds_cancels_and_ends_plus(self, admin):
        await self._paid()
        ctx = _bot_context(['c1'])
        update = make_update('', user_id=ADMIN_ID)
        with _at(NOW + timedelta(days=2)):
            await payments.refund(update, ctx)
            assert not is_plus(_stored())
        ctx.bot.refund_star_payment.assert_awaited_once_with(user_id=USER_ID, telegram_payment_charge_id='c1')
        ctx.bot.edit_user_star_subscription.assert_awaited_once_with(
            user_id=USER_ID, telegram_payment_charge_id='c1', is_canceled=True
        )
        assert PaymentRepository().find('c1')['refunded_at'] is not None
        assert 'Subscription cancelled: yes' in update.message.reply_text.call_args.args[0]

    async def test_a_refused_refund_changes_nothing(self, admin):
        await self._paid()
        ctx = _bot_context(['c1'])
        ctx.bot.refund_star_payment.side_effect = BadRequest('CHARGE_ALREADY_REFUNDED')
        update = make_update('', user_id=ADMIN_ID)
        with _at():
            await payments.refund(update, ctx)
            assert is_plus(_stored())
        assert PaymentRepository().find('c1')['refunded_at'] is None
        assert update.message.reply_text.call_args.args[0] == strings.ADMIN_REFUND_FAILED

    async def test_an_unknown_charge_is_reported(self, admin):
        update = make_update('', user_id=ADMIN_ID)
        await payments.refund(update, _bot_context(['nope']))
        assert update.message.reply_text.call_args.args[0] == strings.ADMIN_REFUND_UNKNOWN

    async def test_a_non_admin_cannot_refund(self, admin):
        await self._paid()
        ctx = _bot_context(['c1'])
        await payments.refund(make_update('', user_id=USER_ID), ctx)
        ctx.bot.refund_star_payment.assert_not_called()


# ---------------------------------------------------------------------------
# /delete with a live subscription
# ---------------------------------------------------------------------------

class TestDeleteCancelsTheSubscription:
    async def _delete(self, ctx):
        update = make_update(DELETE_YES)
        with patch('bot.handlers.journal.deps.analytics_svc'):
            state = await handle_delete_confirmation(update, ctx)
        return state, update

    async def test_the_subscription_is_cancelled_before_the_ledger_is_deleted(self):
        _save_user()
        with _at():
            _record(PaymentService())
            ctx = _bot_context()
            state, update = await self._delete(ctx)
        assert state == ConversationHandler.END
        ctx.bot.edit_user_star_subscription.assert_awaited_once_with(
            user_id=USER_ID, telegram_payment_charge_id='c1', is_canceled=True
        )
        assert PaymentRepository().find('c1') is None
        assert update.message.reply_text.call_args.args[0] == strings.DELETE_DONE

    async def test_a_failed_cancel_still_deletes_and_says_what_to_do(self):
        """Erasure is not held hostage to a Telegram outage."""
        _save_user()
        with _at():
            _record(PaymentService())
            ctx = _bot_context()
            ctx.bot.edit_user_star_subscription.side_effect = BadRequest('nope')
            await self._delete(ctx)
            _, update = await self._delete(_bot_context())  # a retry: nothing left, nothing to cancel
        assert _stored() is None
        assert PaymentRepository().find('c1') is None

    async def test_the_reply_asks_the_user_to_cancel_when_it_failed(self):
        _save_user()
        with _at():
            _record(PaymentService())
            ctx = _bot_context()
            ctx.bot.edit_user_star_subscription.side_effect = BadRequest('nope')
            _, update = await self._delete(ctx)
        assert 'My Stars' in update.message.reply_text.call_args.args[0]

    async def test_a_renewal_after_a_failed_cancel_is_refunded(self):
        """The path that makes a non-blocking cancel safe: the next charge is caught."""
        _save_user()
        with _at():
            _record(PaymentService())
            ctx = _bot_context()
            ctx.bot.edit_user_star_subscription.side_effect = BadRequest('nope')
            await self._delete(ctx)
            renewal_ctx = _bot_context()
            renewal = _payment_update('c2', first=False, expires=NOW + timedelta(days=60))
            with patch('bot.handlers.journal.deps.analytics_svc'):
                await payments.handle_successful_payment(renewal, renewal_ctx)
        renewal_ctx.bot.refund_star_payment.assert_awaited_once_with(
            user_id=USER_ID, telegram_payment_charge_id='c2'
        )
        assert _stored() is None
        from db.db import payments_collection
        assert payments_collection().count_documents({'telegram_id': USER_ID}) == 0

    async def test_no_subscription_means_no_bot_api_call(self):
        _save_user()
        ctx = _bot_context()
        await self._delete(ctx)
        ctx.bot.edit_user_star_subscription.assert_not_called()

    def test_the_prompt_says_the_subscription_is_cancelled(self):
        assert 'subscription is cancelled' in strings.DELETE_CONFIRM_PROMPT


class TestPaySupport:
    async def _text(self) -> str:
        from bot.handlers.commands import paysupport_command
        update = make_update('/paysupport')
        await paysupport_command(update, make_context())
        return update.message.reply_text.call_args.args[0]

    async def test_names_the_configured_contact(self, monkeypatch):
        monkeypatch.setenv('SUPPORT_CONTACT', 'help_bot@example.com')
        text = await self._text()
        assert 'help\\_bot@example.com' in text  # escaped for Markdown
        assert 'My Stars' in text

    async def test_falls_back_when_no_contact_is_set(self, monkeypatch):
        monkeypatch.delenv('SUPPORT_CONTACT', raising=False)
        assert strings.PAYSUPPORT_CONTACT_FALLBACK in await self._text()
