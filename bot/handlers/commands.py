import os

from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

from messages.markdown import escape_md
from messages.strings import HELP_MESSAGE, PAYSUPPORT_CONTACT_FALLBACK, PAYSUPPORT_MESSAGE, PRIVACY_NOTICE


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(HELP_MESSAGE, parse_mode='Markdown')


async def privacy_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(PRIVACY_NOTICE, parse_mode='Markdown')


async def paysupport_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Required by Telegram for any bot that takes payments."""
    contact = (os.environ.get('SUPPORT_CONTACT') or '').strip()
    await update.message.reply_text(
        PAYSUPPORT_MESSAGE.format(contact=escape_md(contact) if contact else PAYSUPPORT_CONTACT_FALLBACK),
        parse_mode='Markdown',
    )


def register(application: Application) -> None:
    application.add_handler(CommandHandler('help', help_command))
    application.add_handler(CommandHandler('privacy', privacy_command))
    application.add_handler(CommandHandler('paysupport', paysupport_command))
