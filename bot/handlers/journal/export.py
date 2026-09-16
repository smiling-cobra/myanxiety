"""/export — the user's recent entries as a file they can take to a therapy session.

Service calls go through `asyncio.to_thread` — see the package docstring. The
file is built without a model call; see `services/export_service.py`.
"""
import asyncio

from telegram import Update
from telegram.ext import ContextTypes

from bot.handlers.journal import deps
from bot.handlers.journal.errors import service_errors
from bot.handlers.journal.states import MAIN_MENU
from bot.keyboards import get_main_menu_keyboard
from messages.strings import EXPORT_CAPTION, EXPORT_EMPTY
from services import analytics_service as analytics
from services.export_service import EXPORT_DAYS


@service_errors('Export')
async def send_export(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    telegram_id = update.effective_user.id
    export = await asyncio.to_thread(deps.export_svc.build, telegram_id)
    count = export.entry_count if export else 0

    # Whether anyone asks for this at all is the question the v0 export exists
    # to answer, so the request is recorded before the empty-state return.
    await asyncio.to_thread(
        deps.analytics_svc.track, analytics.EXPORT_REQUESTED, telegram_id, entry_count=count, days=EXPORT_DAYS
    )

    if export is None:
        await update.message.reply_text(
            EXPORT_EMPTY.format(days=EXPORT_DAYS), parse_mode='Markdown', reply_markup=get_main_menu_keyboard()
        )
        return MAIN_MENU

    await update.message.reply_document(
        document=export.content,
        filename=export.filename,
        caption=EXPORT_CAPTION.format(days=EXPORT_DAYS, count=count, entries='entry' if count == 1 else 'entries'),
        reply_markup=get_main_menu_keyboard(),
    )
    return MAIN_MENU
