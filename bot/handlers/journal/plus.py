"""/plus — what Plus is, where the user stands, and the subscribe button.

Service calls go through `asyncio.to_thread` — see the package docstring. Paying
happens outside the conversation: the button opens a Telegram invoice link, and
the pre-checkout query and the payment itself are handled in
`bot/handlers/payments.py`.

A single-step command that returns to the main menu, like /export. The offer
carries an inline button, and a message can carry only one keyboard, so the
main menu follows in a second message.
"""
import asyncio

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, LabeledPrice, Update
from telegram.ext import ContextTypes

from bot.handlers.journal import deps
from bot.handlers.journal.errors import service_errors
from bot.handlers.journal.main_menu import main_menu_keyboard
from bot.handlers.journal.states import MAIN_MENU
from messages.markdown import escape_md
from messages.strings import (
    MAIN_MENU_MESSAGE,
    PLUS_ACTIVE,
    PLUS_NOT_READY,
    PLUS_OFFER,
    PLUS_SUBSCRIBE_BUTTON,
    PLUS_TRIAL_LINE,
)
from services import analytics_service as analytics
from services.payment_service import PLUS_PAYLOAD, PLUS_PRICE_STARS, STARS_CURRENCY, SUBSCRIPTION_PERIOD
from services.plan_service import SOURCE_SUBSCRIPTION, is_plus, plus_until

_INVOICE_LINK = 'plus_invoice_link'

_FREE = 'free'
_TRIAL = 'trial'
_PLUS = 'plus'


def _date_label(value) -> str:
    return f'{value.day} {value:%B %Y}'


async def invoice_link(context: ContextTypes.DEFAULT_TYPE) -> str:
    """The subscription invoice link, created once per process.

    The payload names the product, not the buyer — the payer is whoever pays,
    read from the payment itself — so one link serves everyone. It is kept in
    `bot_data`, which is not persisted, so a restart simply makes a new one.
    """
    link = context.bot_data.get(_INVOICE_LINK)
    if link is None:
        link = await context.bot.create_invoice_link(
            title='AnxietyJournal Plus',
            description='Replies to every entry, weekly pattern insights and 90-day exports.',
            payload=PLUS_PAYLOAD,
            currency=STARS_CURRENCY,
            prices=[LabeledPrice('Plus — 30 days', PLUS_PRICE_STARS)],
            subscription_period=int(SUBSCRIPTION_PERIOD.total_seconds()),
        )
        context.bot_data[_INVOICE_LINK] = link
    return link


@service_errors('Plus')
async def show_plus(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int | None:
    telegram_id = update.effective_user.id
    user = await asyncio.to_thread(deps.user_svc.get, telegram_id) or {}
    if not user.get('onboarded'):
        # As /settings: before the account exists there is nothing to attach Plus
        # to, and None leaves the onboarding step where it was.
        await update.message.reply_text(PLUS_NOT_READY)
        return None

    until = plus_until(user)
    subscribed = is_plus(user) and user.get('plus_source') == SOURCE_SUBSCRIPTION
    status = _PLUS if subscribed else _TRIAL if is_plus(user) else _FREE
    await asyncio.to_thread(deps.analytics_svc.track, analytics.PLUS_VIEWED, telegram_id, status=status)

    if subscribed:
        await update.message.reply_text(PLUS_ACTIVE.format(date=_date_label(until)), parse_mode='Markdown')
    else:
        text = PLUS_OFFER.format(price=PLUS_PRICE_STARS)
        if status == _TRIAL:
            text += PLUS_TRIAL_LINE.format(date=_date_label(until))
        button = InlineKeyboardButton(
            PLUS_SUBSCRIBE_BUTTON.format(price=PLUS_PRICE_STARS), url=await invoice_link(context)
        )
        await update.message.reply_text(
            text, parse_mode='Markdown', reply_markup=InlineKeyboardMarkup([[button]])
        )

    name = user.get('name') or context.user_data.get('name', 'there')
    await update.message.reply_text(
        MAIN_MENU_MESSAGE.format(name=escape_md(name)),
        parse_mode='Markdown',
        reply_markup=await main_menu_keyboard(telegram_id),
    )
    return MAIN_MENU
