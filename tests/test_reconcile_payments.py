"""Replaying Telegram's Star transactions into the ledger, for payments the handler failed to record."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from telegram import StarTransaction, TransactionPartnerFragment, TransactionPartnerUser, User

from repositories.payment_repo import PaymentRepository
from repositories.user_repo import UserRepository
from scripts.reconcile_payments import fetch_transactions, reconcile
from services.payment_service import PLUS_PAYLOAD, PLUS_PRICE_STARS, PaymentService
from services.plan_service import is_plus

NOW = datetime(2026, 9, 24, 10, 0, tzinfo=timezone.utc)
USER_ID = 12345


def _tx(charge_id='c1', user_id=USER_ID, payload=PLUS_PAYLOAD, period=timedelta(days=30),
        kind='invoice_payment', date=NOW):
    source = TransactionPartnerUser(
        transaction_type=kind, user=User(user_id, 'Sam', False),
        invoice_payload=payload, subscription_period=period,
    )
    return StarTransaction(id=charge_id, amount=PLUS_PRICE_STARS, date=date, source=source)


def _save_user(telegram_id=USER_ID):
    UserRepository().save({'telegram_id': telegram_id, 'name': 'Sam', 'onboarded': True})


def _run(transactions, dry_run=False):
    with patch('services.time_utils.now', return_value=NOW):
        return reconcile(transactions, dry_run=dry_run)


def test_a_missing_payment_is_recorded_and_grants_plus():
    _save_user()
    report = _run([_tx()])
    assert (report.seen, report.recorded, report.orphans) == (1, 1, 0)
    row = PaymentRepository().find('c1')
    assert row['telegram_id'] == USER_ID and row['is_recurring'] is True
    with patch('services.time_utils.now', return_value=NOW):
        assert is_plus(UserRepository().find(USER_ID))
    assert UserRepository().find(USER_ID)['plus_until'].replace(tzinfo=timezone.utc) == NOW + timedelta(days=30)


def test_a_recorded_payment_is_left_alone():
    _save_user()
    with patch('services.time_utils.now', return_value=NOW):
        PaymentService().record(
            USER_ID, charge_id='c1', provider_charge_id=None, amount=PLUS_PRICE_STARS, currency='XTR',
            payload=PLUS_PAYLOAD, is_recurring=True, is_first_recurring=True, expires_at=NOW + timedelta(days=30),
        )
    assert _run([_tx()]).recorded == 0


def test_a_refunded_charge_in_the_ledger_is_not_restored():
    _save_user()
    svc = PaymentService()
    with patch('services.time_utils.now', return_value=NOW):
        svc.record(
            USER_ID, charge_id='c1', provider_charge_id=None, amount=PLUS_PRICE_STARS, currency='XTR',
            payload=PLUS_PAYLOAD, is_recurring=True, is_first_recurring=True, expires_at=NOW + timedelta(days=30),
        )
        svc.mark_refunded('c1')
    _run([_tx()])
    with patch('services.time_utils.now', return_value=NOW):
        assert not is_plus(UserRepository().find(USER_ID))


def test_a_payer_with_no_account_is_counted_not_stored():
    report = _run([_tx()])
    assert (report.recorded, report.orphans) == (0, 1)
    assert PaymentRepository().find('c1') is None


def test_other_transactions_are_ignored():
    _save_user()
    fragment = StarTransaction(id='w1', amount=500, date=NOW, receiver=TransactionPartnerFragment())
    report = _run([_tx('x1', payload='something_else'), _tx('x2', kind='paid_media_payment'), fragment])
    assert report.seen == 0
    assert PaymentRepository().find('x1') is None


def test_a_dry_run_reports_and_writes_nothing():
    _save_user()
    report = _run([_tx()], dry_run=True)
    assert report.recorded == 1
    assert PaymentRepository().find('c1') is None
    assert 'plus_until' not in UserRepository().find(USER_ID)


def test_a_one_off_payment_gets_one_period():
    _save_user()
    _run([_tx(period=None)])
    assert PaymentRepository().find('c1')['is_recurring'] is False
    assert UserRepository().find(USER_ID)['plus_until'].replace(tzinfo=timezone.utc) == NOW + timedelta(days=30)


async def test_fetch_pages_until_a_short_page():
    bot = MagicMock()
    pages = [list(range(100)), list(range(100)), list(range(7))]
    bot.get_star_transactions = AsyncMock(side_effect=[SimpleNamespace(transactions=p) for p in pages])
    assert len(await fetch_transactions(bot)) == 207
    offsets = [c.kwargs['offset'] for c in bot.get_star_transactions.call_args_list]
    assert offsets == [0, 100, 200]
