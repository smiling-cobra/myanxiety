"""Telegram Stars payments for Plus, and the admin commands around them.

These run outside the journal `ConversationHandler`, in handler group -1, so
they never touch conversation state: a payment can land while the user is
mid-check-in, and the check-in must carry on undisturbed. A pre-checkout query
has no chat at all, so the conversation could not route it anyway.

The offer itself, `/plus`, is part of the conversation — see
`bot/handlers/journal/plus.py`. The rules live in `services/payment_service.py`.

**A pre-checkout query must always be answered**, within ten seconds, or the
user's payment fails with a timeout. Every path answers, including the failure
of the check itself, which refuses.

Admin commands are for the ids in `ADMIN_TELEGRAM_IDS` only, and everyone else
gets no reply at all, so their existence isn't advertised:

* `/admin_plus on [days]` and `/admin_plus off` move the admin's own Plus, to
  test both sides of every gate without paying;
* `/refund <charge_id>` refunds a payment in Stars, cancels the subscription it
  belongs to, and ends that user's Plus.
"""
import asyncio
import logging
from datetime import timedelta

from telegram import Update
from telegram.error import TelegramError
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, PreCheckoutQueryHandler, filters

from bot.handlers.journal import deps
from bot.handlers.journal.account import cancel_subscription
from config import admin_ids
from messages.strings import (
    ADMIN_PLUS_OFF,
    ADMIN_PLUS_ON,
    ADMIN_PLUS_USAGE,
    ADMIN_REFUND_DONE,
    ADMIN_REFUND_FAILED,
    ADMIN_REFUND_UNKNOWN,
    ADMIN_REFUND_USAGE,
    PLUS_CHECKOUT_NO_ACCOUNT,
    PLUS_CHECKOUT_REFUSED,
    PLUS_WELCOME,
)
from services import analytics_service as analytics
from services import time_utils
from services.payment_service import REJECT_NO_ACCOUNT
from services.plan_service import SOURCE_ADMIN

logger = logging.getLogger(__name__)

_DEFAULT_ADMIN_PLUS_DAYS = 30
_CHECK_FAILED = 'check_failed'


def _date_label(value) -> str:
    return f'{value.day} {value:%B %Y}'


async def handle_pre_checkout(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.pre_checkout_query
    telegram_id = query.from_user.id
    try:
        problem = await asyncio.to_thread(
            deps.payment_svc.checkout_problem,
            telegram_id, query.invoice_payload, query.currency, query.total_amount,
        )
    except Exception:
        logger.exception('Pre-checkout check failed for user %s — refusing the payment.', telegram_id)
        problem = _CHECK_FAILED

    if problem is None:
        await query.answer(ok=True)
        return

    await query.answer(
        ok=False,
        error_message=PLUS_CHECKOUT_NO_ACCOUNT if problem == REJECT_NO_ACCOUNT else PLUS_CHECKOUT_REFUSED,
    )
    await asyncio.to_thread(
        deps.analytics_svc.track, analytics.PLUS_CHECKOUT_REJECTED, telegram_id, reason=problem
    )


async def handle_successful_payment(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Record the payment and extend Plus. The entitled user is always the payer.

    Deliberately not wrapped in a catch-all: if recording fails, the global
    error handler logs it and apologises, and the ledger can be reconciled
    against Telegram's own transaction list. Swallowing it here would hide a
    paid-for Plus that never arrived.
    """
    payment = update.message.successful_payment
    telegram_id = update.effective_user.id
    charge_id = payment.telegram_payment_charge_id
    result = await asyncio.to_thread(
        deps.payment_svc.record,
        telegram_id,
        charge_id=charge_id,
        provider_charge_id=payment.provider_payment_charge_id,
        amount=payment.total_amount,
        currency=payment.currency,
        payload=payment.invoice_payload,
        is_recurring=bool(payment.is_recurring),
        is_first_recurring=bool(payment.is_first_recurring),
        expires_at=payment.subscription_expiration_date,
    )
    if result.orphan:
        await _refund_orphan(context, telegram_id, charge_id)
        return
    if not result.new:
        logger.info('Payment %s for user %s was already recorded.', charge_id, telegram_id)
        return

    await asyncio.to_thread(
        deps.analytics_svc.track,
        analytics.PLUS_PURCHASED,
        telegram_id,
        renewal=result.renewal,
        amount=payment.total_amount,
    )
    # A renewal already shows as a service message from Telegram; a thank-you
    # every month would be noise.
    if not result.renewal:
        await update.message.reply_text(
            PLUS_WELCOME.format(date=_date_label(result.plus_until)), parse_mode='Markdown'
        )


async def _refund_orphan(context: ContextTypes.DEFAULT_TYPE, telegram_id: int, charge_id: str) -> None:
    """Give back a charge for an account that no longer exists, and stop the renewals.

    Nothing is sent to the user: they deleted their account, and Telegram shows
    the refund itself. A failure is logged with the charge id so it can be
    refunded by hand; there is no ledger row to find it by.
    """
    await cancel_subscription(context, telegram_id, charge_id)
    try:
        await context.bot.refund_star_payment(user_id=telegram_id, telegram_payment_charge_id=charge_id)
    except TelegramError:
        logger.exception('Could not refund charge %s for deleted user %s — refund it by hand.', charge_id, telegram_id)
        return
    logger.warning('Refunded charge %s from user %s, who has no account.', charge_id, telegram_id)
    await asyncio.to_thread(deps.analytics_svc.track, analytics.PLUS_ORPHAN_REFUNDED)


def _is_admin(update: Update) -> bool:
    return update.effective_user is not None and update.effective_user.id in admin_ids()


async def admin_plus(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_admin(update):
        return
    telegram_id = update.effective_user.id
    args = [a.lower() for a in (context.args or [])]

    if args[:1] == ['off'] and len(args) == 1:
        await asyncio.to_thread(deps.plan_svc.set_until, telegram_id, time_utils.now(), SOURCE_ADMIN)
        await update.message.reply_text(ADMIN_PLUS_OFF)
        return

    if args[:1] == ['on'] and len(args) <= 2 and (len(args) == 1 or args[1].isdigit()):
        days = int(args[1]) if len(args) == 2 else _DEFAULT_ADMIN_PLUS_DAYS
        until = time_utils.now() + timedelta(days=days)
        await asyncio.to_thread(deps.plan_svc.set_until, telegram_id, until, SOURCE_ADMIN)
        await asyncio.to_thread(
            deps.analytics_svc.track, analytics.PLUS_GRANTED, telegram_id, source=SOURCE_ADMIN, days=days
        )
        await update.message.reply_text(ADMIN_PLUS_ON.format(date=_date_label(until)))
        return

    await update.message.reply_text(ADMIN_PLUS_USAGE)


async def refund(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_admin(update):
        return
    if len(context.args or []) != 1:
        await update.message.reply_text(ADMIN_REFUND_USAGE)
        return

    charge_id = context.args[0]
    payment = await asyncio.to_thread(deps.payment_svc.find, charge_id)
    if payment is None:
        await update.message.reply_text(ADMIN_REFUND_UNKNOWN)
        return

    user_id = payment['telegram_id']
    try:
        await context.bot.refund_star_payment(user_id=user_id, telegram_payment_charge_id=charge_id)
    except TelegramError:
        logger.exception('Refund of %s for user %s was refused by Telegram.', charge_id, user_id)
        await update.message.reply_text(ADMIN_REFUND_FAILED)
        return

    # The Stars are back; now make sure the subscription can't charge again.
    # Best-effort: it may already be cancelled, or not be a subscription at all.
    cancelled = await cancel_subscription(context, user_id, charge_id)
    await asyncio.to_thread(deps.payment_svc.mark_refunded, charge_id)
    await asyncio.to_thread(deps.analytics_svc.track, analytics.PLUS_REFUNDED, user_id)
    await update.message.reply_text(
        ADMIN_REFUND_DONE.format(amount=payment['amount'], user=user_id, cancelled='yes' if cancelled else 'no')
    )


def register(application: Application) -> None:
    group = -1
    application.add_handler(PreCheckoutQueryHandler(handle_pre_checkout), group=group)
    application.add_handler(MessageHandler(filters.SUCCESSFUL_PAYMENT, handle_successful_payment), group=group)
    application.add_handler(CommandHandler('admin_plus', admin_plus), group=group)
    application.add_handler(CommandHandler('refund', refund), group=group)
