"""Global error handler.

Without one, an exception escaping a handler is logged by python-telegram-bot
and nothing else happens: the user sees no reply at all and is left waiting on a
bot that has silently given up on their message.
"""
import asyncio
import logging

from telegram import Update
from telegram.ext import Application, ContextTypes

from bot.handlers.journal import deps
from bot.keyboards import get_main_menu_keyboard
from messages.strings import ERROR_GENERIC
from services import analytics_service as analytics

logger = logging.getLogger(__name__)


async def handle_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.error('Unhandled exception while processing an update', exc_info=context.error)

    message = update.effective_message if isinstance(update, Update) else None
    user = update.effective_user if isinstance(update, Update) else None

    # An uncaught exception is the one failure mode the product cannot see any
    # other way: the user just stops replying, and nothing distinguishes that
    # from losing interest. Only the exception's type is recorded — its message
    # can quote whatever the user typed.
    await asyncio.to_thread(
        deps.analytics_svc.track,
        analytics.HANDLER_ERROR,
        user.id if user else None,
        error_type=type(context.error).__name__,
    )
    if message is None:  # e.g. a failure inside a job, with no update to answer
        return

    # The main-menu keyboard re-anchors the user: whatever state the conversation
    # was in, their next tap is something the bot can act on.
    try:
        await message.reply_text(ERROR_GENERIC, reply_markup=get_main_menu_keyboard())
    except Exception:
        logger.exception('Could not deliver the error notice to the user')


def register(application: Application) -> None:
    application.add_error_handler(handle_error)
