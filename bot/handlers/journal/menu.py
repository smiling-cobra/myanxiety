import asyncio

from telegram import ReplyKeyboardRemove, Update
from telegram.ext import ContextTypes, ConversationHandler

from bot.handlers.journal import deps
from bot.handlers.journal.main_menu import main_menu_keyboard
from bot.handlers.journal.onboarding import start
from bot.handlers.journal.states import CHECK_IN_MOOD, MAIN_MENU
from bot.handlers.journal.export import send_export
from bot.handlers.journal.views import show_history, show_stats, show_weekly_summary
from bot.keyboards import (
    ENTRY_CHOICES, EXPORT, HELP, HISTORY, MAIN_MENU_CHOICES, STATS, WEEKLY_SUMMARY, get_mood_keyboard,
)
from messages.strings import (
    CANCEL_MESSAGE, CHECK_IN_MOOD_PROMPT, HELP_MESSAGE, MAIN_MENU_MESSAGE, NOTE_MOOD_PROMPT,
)


def _name(context: ContextTypes.DEFAULT_TYPE) -> str:
    return context.user_data.get('name', 'there')


async def handle_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    choice = update.message.text
    name = _name(context)

    if choice in ENTRY_CHOICES:
        # Wording only, and never from the label that was tapped: a keyboard can
        # outlive the day it was sent on. Whether the entry counts as the daily
        # check-in or a note is decided when it is saved, which may fall after
        # local midnight.
        noted = await asyncio.to_thread(deps.journal_svc.checked_in_today, update.effective_user.id)
        prompt = NOTE_MOOD_PROMPT if noted else CHECK_IN_MOOD_PROMPT
        await update.message.reply_text(prompt.format(name=name), reply_markup=get_mood_keyboard())
        return CHECK_IN_MOOD

    if choice == HISTORY:
        return await show_history(update, context)

    if choice == STATS:
        return await show_stats(update, context)

    if choice == WEEKLY_SUMMARY:
        return await show_weekly_summary(update, context)

    if choice == EXPORT:
        return await send_export(update, context)

    if choice == HELP:
        await update.message.reply_text(HELP_MESSAGE, parse_mode='Markdown')
        return MAIN_MENU

    return MAIN_MENU


async def recover_state(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Entry point for a text message that belongs to no active conversation.

    Reached when persisted state is genuinely gone, but also after a normal
    `/cancel` or a first-ever message — the three are indistinguishable from
    here, so this apologises for nothing and simply re-anchors the user.
    """
    telegram_id = update.effective_user.id
    user = await asyncio.to_thread(deps.user_svc.get, telegram_id)

    if not (user and user.get('onboarded')):
        return await start(update, context)

    # start() would re-fetch the user to learn this; we already have it.
    context.user_data.setdefault('name', user['name'])

    # A reply keyboard outlives the conversation that sent it, so the message
    # that landed here is most often a menu tap. Act on it rather than making
    # them tap the same button twice.
    if update.message.text in MAIN_MENU_CHOICES:
        return await handle_main_menu(update, context)

    await update.message.reply_text(
        MAIN_MENU_MESSAGE.format(name=user['name']),
        reply_markup=await main_menu_keyboard(telegram_id),
    )
    return MAIN_MENU


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text(
        CANCEL_MESSAGE.format(name=_name(context)),
        reply_markup=ReplyKeyboardRemove(),
    )
    return ConversationHandler.END
