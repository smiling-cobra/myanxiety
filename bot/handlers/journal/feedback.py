"""/feedback — one message from the user to the people who run the bot.

Service calls go through `asyncio.to_thread` — see the package docstring.

Two steps: the command (or the Settings button) asks for a message, and the
next text is stored, forwarded to every id in `ADMIN_TELEGRAM_IDS`, and
acknowledged. The stored row is the record; a forward that fails is logged and
never shown to the user.

Feedback is text someone wrote, and people write distress wherever there is a
text box, so it goes through the crisis lexicon exactly as an entry does, before
anything that can fail.

`source` (command, settings or prompt) is kept in memory only: it is not on the
persistence allowlist, so a restart mid-flow records the message as `command`.
"""
import asyncio
import logging

from telegram import Update
from telegram.ext import ContextTypes

from bot.handlers.journal import deps
from bot.handlers.journal.checkin import _CONTENT_TRIGGER, FEEDBACK_ASKED, _send_crisis_resources
from bot.handlers.journal.errors import service_errors
from bot.handlers.journal.main_menu import main_menu_keyboard
from bot.handlers.journal.states import FEEDBACK_TEXT, MAIN_MENU
from bot.keyboards import BACK, get_back_keyboard
from config import admin_ids
from messages.markdown import escape_md
from messages.strings import (
    FEEDBACK_ADMIN_FORWARD,
    FEEDBACK_LIMIT_REACHED,
    FEEDBACK_NOT_READY,
    FEEDBACK_PROMPT,
    FEEDBACK_THANKS,
    FEEDBACK_TOO_LONG,
    MAIN_MENU_MESSAGE,
)
from services import analytics_service as analytics
from services.feedback_service import MAX_FEEDBACK_LENGTH
from services.safety import detect_crisis

logger = logging.getLogger(__name__)

SOURCE_COMMAND = 'command'
SOURCE_SETTINGS = 'settings'
SOURCE_PROMPT = 'prompt'

# user_data key, not persisted. `FEEDBACK_ASKED` is set by the one-time ask in
# checkin.py, so a /feedback that follows it is counted as its conversion.
_SOURCE = 'feedback_source'


@service_errors('Feedback')
async def request_feedback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int | None:
    return await _request(update, context, SOURCE_COMMAND)


async def request_feedback_from_settings(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int | None:
    """The Settings button. Called from `handle_settings_choice`, which carries the error handling."""
    return await _request(update, context, SOURCE_SETTINGS)


async def _request(update: Update, context: ContextTypes.DEFAULT_TYPE, source: str) -> int | None:
    telegram_id = update.effective_user.id
    user = await asyncio.to_thread(deps.user_svc.get, telegram_id) or {}
    if not user.get('onboarded'):
        # As /settings: None leaves an onboarding step where it was.
        await update.message.reply_text(FEEDBACK_NOT_READY)
        return None

    if not await asyncio.to_thread(deps.feedback_svc.can_submit, telegram_id):
        await update.message.reply_text(FEEDBACK_LIMIT_REACHED, reply_markup=await main_menu_keyboard(telegram_id))
        return MAIN_MENU

    if source == SOURCE_COMMAND and context.user_data.pop(FEEDBACK_ASKED, False):
        source = SOURCE_PROMPT
    context.user_data[_SOURCE] = source
    await update.message.reply_text(
        FEEDBACK_PROMPT.format(limit=MAX_FEEDBACK_LENGTH), reply_markup=get_back_keyboard()
    )
    return FEEDBACK_TEXT


@service_errors('Feedback')
async def handle_feedback_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    telegram_id = update.effective_user.id
    text = update.message.text.strip()

    if text == BACK or not text:
        context.user_data.pop(_SOURCE, None)
        name = context.user_data.get('name', 'there')
        await update.message.reply_text(
            MAIN_MENU_MESSAGE.format(name=escape_md(name)),
            parse_mode='Markdown',
            reply_markup=await main_menu_keyboard(telegram_id),
        )
        return MAIN_MENU

    # Before anything that can fail, as in checkin.py.
    categories = detect_crisis(text)
    if categories:
        await _send_crisis_resources(update, telegram_id, [_CONTENT_TRIGGER], categories)

    if len(text) > MAX_FEEDBACK_LENGTH:
        await update.message.reply_text(
            FEEDBACK_TOO_LONG.format(limit=MAX_FEEDBACK_LENGTH, length=len(text)), reply_markup=get_back_keyboard()
        )
        return FEEDBACK_TEXT

    source = context.user_data.pop(_SOURCE, SOURCE_COMMAND)
    if not await asyncio.to_thread(deps.feedback_svc.submit, telegram_id, text):
        await update.message.reply_text(FEEDBACK_LIMIT_REACHED, reply_markup=await main_menu_keyboard(telegram_id))
        return MAIN_MENU

    await asyncio.to_thread(
        deps.analytics_svc.track, analytics.FEEDBACK_SENT, telegram_id, text_length=len(text), source=source
    )
    await _forward_to_admins(context, telegram_id, text, source)
    await update.message.reply_text(FEEDBACK_THANKS, reply_markup=await main_menu_keyboard(telegram_id))
    return MAIN_MENU


async def _forward_to_admins(context: ContextTypes.DEFAULT_TYPE, telegram_id: int, text: str, source: str) -> None:
    """Send a copy to each admin, in plain text. Never raises: the stored row is the record."""
    admins = admin_ids()
    if not admins:
        logger.info('Feedback from user %s stored; ADMIN_TELEGRAM_IDS is empty, so nobody was notified.', telegram_id)
        return
    plus = await asyncio.to_thread(deps.plan_svc.is_plus, telegram_id)
    message = FEEDBACK_ADMIN_FORWARD.format(
        telegram_id=telegram_id, source=source, plan='plus' if plus else 'free', text=text
    )
    for admin in admins:
        try:
            await context.bot.send_message(chat_id=admin, text=message)
        except Exception:
            logger.warning('Could not forward feedback from user %s to admin %s.', telegram_id, admin, exc_info=True)
