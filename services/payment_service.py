"""Selling Plus for Telegram Stars: checkout rules, the ledger, refunds.

Telegram objects stay in the handler (`bot/handlers/payments.py`); this service
takes plain values, so the rules can be tested without a Bot.

There is one product, a monthly subscription. A subscription can only be sold
through an invoice *link* (`create_invoice_link` with `subscription_period`),
and Telegram renews it by itself: each renewal arrives as another
`successful_payment` carrying the new `subscription_expiration_date`. The bot
is never told about a cancellation, so the ledger and `plus_until` are all it
needs — access lapses on its own when renewals stop.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta

from repositories.payment_repo import PaymentRepository
from repositories.user_repo import UserRepository
from services import time_utils
from services.plan_service import SOURCE_SUBSCRIPTION, PlanService, plus_until

logger = logging.getLogger(__name__)

PLUS_PAYLOAD = 'plus_monthly_v1'
PLUS_PRICE_STARS = 250
STARS_CURRENCY = 'XTR'
# The only period the Bot API accepts for a Stars subscription.
SUBSCRIPTION_PERIOD = timedelta(days=30)

# Closed vocabulary for `plus_checkout_rejected`.
REJECT_UNKNOWN_PAYLOAD = 'unknown_payload'
REJECT_WRONG_CURRENCY = 'wrong_currency'
REJECT_WRONG_AMOUNT = 'wrong_amount'
REJECT_NO_ACCOUNT = 'no_account'


@dataclass(frozen=True)
class PaymentResult:
    new: bool               # False for a redelivered update already in the ledger
    renewal: bool           # an automatic renewal, not a purchase the user just made
    plus_until: datetime


class PaymentService:
    def __init__(self):
        self._payments = PaymentRepository()
        self._users = UserRepository()
        self._plan = PlanService()

    def checkout_problem(self, telegram_id: int, payload: str, currency: str, amount: int) -> str | None:
        """Why a pre-checkout query must be refused, or None to approve it.

        The amount is checked against today's price, so a link created before a
        price change cannot be paid at the old one. The payer needs a finished
        account: Plus is stored on the user record, and a payment for an account
        that doesn't exist would be taken with nothing to show for it.
        """
        if payload != PLUS_PAYLOAD:
            return REJECT_UNKNOWN_PAYLOAD
        if currency != STARS_CURRENCY:
            return REJECT_WRONG_CURRENCY
        if amount != PLUS_PRICE_STARS:
            return REJECT_WRONG_AMOUNT
        user = self._users.find(telegram_id)
        if not user or not user.get('onboarded'):
            return REJECT_NO_ACCOUNT
        return None

    def record(
        self,
        telegram_id: int,
        *,
        charge_id: str,
        provider_charge_id: str | None,
        amount: int,
        currency: str,
        payload: str,
        is_recurring: bool,
        is_first_recurring: bool,
        expires_at: datetime | None,
    ) -> PaymentResult:
        """Write a payment to the ledger and extend Plus to the period it paid for.

        A charge already in the ledger is extended again, which is idempotent
        (`PlanService.extend` never shortens). That lets a replay — the reconcile
        script, or an update redelivered after a hard crash — repair a crash
        between the insert and the extension. A refunded
        charge is never extended again: a replay must not undo a refund.
        """
        now = time_utils.now()
        until = time_utils.as_utc(expires_at) if expires_at else now + SUBSCRIPTION_PERIOD
        new = self._payments.record({
            'telegram_id': telegram_id,
            'telegram_payment_charge_id': charge_id,
            'provider_payment_charge_id': provider_charge_id,
            'amount': amount,
            'currency': currency,
            'payload': payload,
            'is_recurring': bool(is_recurring),
            'is_first_recurring': bool(is_first_recurring),
            'expires_at': until,
            'created_at': now,
            'refunded_at': None,
        })
        if not new:
            stored = self._payments.find(charge_id)
            if stored is not None and stored.get('refunded_at') is not None:
                return PaymentResult(
                    new=False, renewal=False, plus_until=plus_until(self._users.find(telegram_id)) or now
                )
        stored_until = self._plan.extend(telegram_id, until, SOURCE_SUBSCRIPTION)
        return PaymentResult(
            new=new,
            renewal=bool(is_recurring) and not is_first_recurring,
            plus_until=stored_until,
        )

    def live_subscription_charge(self, telegram_id: int) -> str | None:
        """The charge id naming a subscription that may still renew, or None.

        Only a subscription whose paid period hasn't ended can renew, so older
        rows are ignored. Whether the user already cancelled it in Telegram is
        unknowable from here; cancelling twice is harmless.
        """
        payment = self._payments.latest_recurring(telegram_id)
        if not payment or time_utils.as_utc(payment['expires_at']) <= time_utils.now():
            return None
        return payment['telegram_payment_charge_id']

    def find(self, charge_id: str) -> dict | None:
        return self._payments.find(charge_id)

    def mark_refunded(self, charge_id: str) -> dict | None:
        """Record a refund Telegram has already made, and end that user's Plus now."""
        payment = self._payments.find(charge_id)
        if payment is None:
            return None
        now = time_utils.now()
        self._payments.mark_refunded(charge_id, now)
        self._plan.set_until(payment['telegram_id'], now, SOURCE_SUBSCRIPTION)
        return payment
