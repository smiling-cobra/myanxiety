"""Replay Telegram's Star transactions into the payments ledger.

A `successful_payment` update is delivered once: if recording it fails, the
user has paid and the bot has no row and no Plus for them. The handler logs
`PLUS_UNRECORDED charge=… user=…` when that happens. This script repairs it
from Telegram's own record (`getStarTransactions`), which is the financial
record of truth anyway:

    fly ssh console -C "python -m scripts.reconcile_payments --dry-run <charge_id> ..."
    fly ssh console -C "python -m scripts.reconcile_payments <charge_id> ..."

Only the charges named on the command line are considered — the ids from the
`PLUS_UNRECORDED` log lines. There is no scan of every transaction: /delete
removes a user's ledger rows on purpose, and a user who deletes and later signs
up again would have that erased history written back by a scan, which can't
tell a lost payment from a deleted one. A named charge that is a Plus invoice
payment missing from the ledger is recorded through `PaymentService.record`, so
Plus is extended exactly as the handler would have done it. A charge already in
the ledger and not refunded is replayed the same way: `PLUS_UNRECORDED` is also
logged when the insert succeeded and the extension after it failed, and only a
replay repairs that. Idempotent: `extend` never shortens, and a refunded charge
is left alone. A charge whose payer has no account is only counted — the
payment handler already refunds those, and this script sends nothing and
refunds nothing.

A charge refunded outside the bot (not via /refund) and never recorded would be
recorded as paid. Refund it through /refund afterwards, which is safe to repeat.

Needs TELEGRAM_TOKEN and MONGODB_URI. It makes no getUpdates call, so it can
run while the bot is polling.
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import os
from dataclasses import dataclass
from datetime import timedelta

from dotenv import load_dotenv

logger = logging.getLogger(__name__)

_PAGE = 100
_INVOICE_PAYMENT = 'invoice_payment'


@dataclass
class ReconcileReport:
    seen: int = 0            # named charges that are Plus payments in Telegram's list
    not_found: int = 0       # named charges with no Plus payment at Telegram
    recorded: int = 0        # missing from the ledger, now recorded (or would be, on a dry run)
    replayed: int = 0        # in the ledger, unrefunded, its extension replayed (or would be)
    orphans: int = 0         # missing, but the payer has no account


async def fetch_transactions(bot) -> list:
    """Every Star transaction the bot has, oldest first, one page at a time."""
    transactions, offset = [], 0
    while True:
        page = (await bot.get_star_transactions(offset=offset, limit=_PAGE)).transactions
        transactions.extend(page)
        if len(page) < _PAGE:
            return transactions
        offset += len(page)


def _plus_payment(transaction):
    """The paying user's partner record if this is an incoming Plus payment, else None."""
    from telegram import TransactionPartnerUser

    from services.payment_service import PLUS_PAYLOAD

    source = transaction.source
    if not isinstance(source, TransactionPartnerUser):
        return None
    if source.transaction_type != _INVOICE_PAYMENT or source.invoice_payload != PLUS_PAYLOAD:
        return None
    return source


def _period(source) -> timedelta | None:
    period = source.subscription_period
    if period is None or isinstance(period, timedelta):
        return period
    return timedelta(seconds=period)


def _count(report: ReconcileReport, charge_id: str, telegram_id: int, in_ledger: bool) -> None:
    if in_ledger:
        report.replayed += 1
        logger.info('Charge %s from user %s is in the ledger; replaying it.', charge_id, telegram_id)
    else:
        report.recorded += 1
        logger.info('Charge %s from user %s is missing from the ledger.', charge_id, telegram_id)


def reconcile(transactions, charge_ids, dry_run: bool = False) -> ReconcileReport:
    """Record each charge in `charge_ids` that is a Plus payment in `transactions` and missing from the ledger."""
    from repositories.user_repo import UserRepository
    from services.payment_service import STARS_CURRENCY, SUBSCRIPTION_PERIOD, PaymentService

    payments, users = PaymentService(), UserRepository()
    report = ReconcileReport()
    wanted = set(charge_ids)
    for transaction in transactions:
        if transaction.id not in wanted:
            continue
        source = _plus_payment(transaction)
        if source is None:
            continue
        wanted.discard(transaction.id)
        report.seen += 1
        stored = payments.find(transaction.id)
        if stored is not None and stored.get('refunded_at') is not None:
            continue

        telegram_id = source.user.id
        if users.find(telegram_id) is None:
            report.orphans += 1
            logger.warning('Charge %s from user %s has no account — not recorded.', transaction.id, telegram_id)
            continue

        _count(report, transaction.id, telegram_id, in_ledger=stored is not None)
        if dry_run:
            continue
        period = _period(source)
        payments.record(
            telegram_id,
            charge_id=transaction.id,
            provider_charge_id=None,
            amount=transaction.amount,
            currency=STARS_CURRENCY,
            payload=source.invoice_payload,
            is_recurring=period is not None,
            # Unknowable from the transaction list, and nothing reads it once
            # the payment is recorded: it only chose whether to say thank you.
            is_first_recurring=False,
            expires_at=transaction.date + (period or SUBSCRIPTION_PERIOD),
        )
    report.not_found = len(wanted)
    if wanted:
        logger.warning('Not Plus payments at Telegram, nothing to do: %s', ', '.join(sorted(wanted)))
    return report


async def _run(charge_ids: list[str], dry_run: bool) -> ReconcileReport:
    from telegram import Bot

    async with Bot(os.environ['TELEGRAM_TOKEN']) as bot:
        transactions = await fetch_transactions(bot)
    return await asyncio.to_thread(reconcile, transactions, charge_ids, dry_run)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format='%(levelname)s %(message)s')
    load_dotenv()
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('charge_ids', nargs='+', metavar='charge_id', help='from a PLUS_UNRECORDED log line')
    parser.add_argument('--dry-run', action='store_true', help='report missing payments without writing')
    args = parser.parse_args()

    report = asyncio.run(_run(args.charge_ids, args.dry_run))
    verb = 'would be recorded' if args.dry_run else 'recorded'
    logger.info(
        '%d named charge(s) found at Telegram, %d not found; %d missing and %s; '
        '%d already recorded and replayed; %d from users with no account.',
        report.seen, report.not_found, report.recorded, verb, report.replayed, report.orphans,
    )


if __name__ == '__main__':
    main()
