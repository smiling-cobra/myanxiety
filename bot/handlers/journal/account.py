"""/delete — remove everything the bot stores about a user.

Service calls go through `asyncio.to_thread` — see the package docstring. The
fan-out itself, and the list of places it reaches, live in
`services/account_service.py`.

Deletion is confirmed with an exact button press. Anything else — a typed
"yes", a stray tap on the other button, a new command — cancels, because the
only unrecoverable mistake here is deleting when the user didn't mean it.

Two stores are outside the database and are cleared here rather than in the
service, because only a handler can reach them:

* the in-memory `user_data` python-telegram-bot holds for the user, which the
  persistence layer would otherwise write straight back on its next flush; and
* the conversation state, which is ended by returning `ConversationHandler.END`
  — that is what removes the stored state row for good.
"""
import asyncio
import logging

from telegram import ReplyKeyboardRemove, Update
from telegram.ext import ContextTypes, ConversationHandler

from bot.handlers.journal import deps
from bot.handlers.journal.states import DELETE_CONFIRM, MAIN_MENU
from bot.keyboards import DELETE_YES, get_delete_keyboard, get_main_menu_keyboard
from messages.strings import DELETE_CANCELLED, DELETE_CONFIRM_PROMPT, DELETE_DONE, DELETE_FAILED
from services import analytics_service as analytics

logger = logging.getLogger(__name__)


async def request_delete(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text(DELETE_CONFIRM_PROMPT, parse_mode='Markdown', reply_markup=get_delete_keyboard())
    return DELETE_CONFIRM


async def handle_delete_confirmation(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    telegram_id = update.effective_user.id

    if update.message.text != DELETE_YES:
        return await _cancel(update, telegram_id)

    try:
        removed = await asyncio.to_thread(deps.account_svc.delete_everything, telegram_id)
    except Exception:
        # Partial by definition: the service attempts every step before raising.
        # The keyboard is removed rather than restored — the account may already
        # be gone, and a menu would invite a check-in into a half-deleted one.
        logger.exception('Account deletion incomplete for user %s', telegram_id)
        await update.message.reply_text(DELETE_FAILED, reply_markup=ReplyKeyboardRemove())
        return ConversationHandler.END

    context.user_data.clear()
    context.application.drop_user_data(telegram_id)

    await asyncio.to_thread(
        deps.analytics_svc.track, analytics.ACCOUNT_DELETED, None, entry_count=removed.get('entries', 0)
    )
    await update.message.reply_text(DELETE_DONE, reply_markup=ReplyKeyboardRemove())
    return ConversationHandler.END


async def _cancel(update: Update, telegram_id: int) -> int:
    await asyncio.to_thread(deps.analytics_svc.track, analytics.DELETE_CANCELLED, telegram_id)

    # /delete is reachable mid-onboarding, where there is no main menu to go back to.
    user = await asyncio.to_thread(deps.user_svc.get, telegram_id)
    if user and user.get('onboarded'):
        await update.message.reply_text(DELETE_CANCELLED, reply_markup=get_main_menu_keyboard())
        return MAIN_MENU

    await update.message.reply_text(DELETE_CANCELLED, reply_markup=ReplyKeyboardRemove())
    return ConversationHandler.END
