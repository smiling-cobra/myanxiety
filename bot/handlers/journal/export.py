"""The therapy-session surfaces: /export, and /flag to mark an entry for it.

Service calls go through `asyncio.to_thread` — see the package docstring. The
file is built without a model call; see `services/export/`.
"""
import asyncio

from telegram import Update
from telegram.ext import ContextTypes

from bot.handlers.journal import deps
from bot.handlers.journal.errors import service_errors
from bot.handlers.journal.states import MAIN_MENU
from bot.handlers.journal.main_menu import main_menu_keyboard
from messages.strings import EXPORT_CAPTION, EXPORT_EMPTY, EXPORT_PLUS_LINE, FLAG_CLEARED, FLAG_NO_ENTRY, FLAG_SET
from services import analytics_service as analytics
from services.export import EXPORT_DAYS, PLUS_EXPORT_DAYS
from services.time_utils import resolve_timezone, to_local


@service_errors('Export')
async def send_export(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    telegram_id = update.effective_user.id
    # The 30-day window is free for good; Plus looks further back.
    plus = await asyncio.to_thread(deps.plan_svc.is_plus, telegram_id)
    days = PLUS_EXPORT_DAYS if plus else EXPORT_DAYS
    export = await asyncio.to_thread(deps.export_svc.build, telegram_id, days)
    count = export.entry_count if export else 0

    # Whether anyone asks for this at all is the question the v0 export exists
    # to answer, so the request is recorded before the empty-state return.
    await asyncio.to_thread(
        deps.analytics_svc.track,
        analytics.EXPORT_REQUESTED,
        telegram_id,
        entry_count=count,
        flagged_count=export.flagged_count if export else 0,
        days=days,
        plus=plus,
    )

    if export is None:
        await update.message.reply_text(
            EXPORT_EMPTY.format(days=days),
            parse_mode='Markdown',
            reply_markup=await main_menu_keyboard(telegram_id),
        )
        return MAIN_MENU

    caption = EXPORT_CAPTION.format(days=days, count=count, entries='entry' if count == 1 else 'entries')
    if not plus:
        caption += EXPORT_PLUS_LINE
        await asyncio.to_thread(deps.analytics_svc.track, analytics.PAYWALL_SHOWN, telegram_id, surface='export')
    await update.message.reply_document(
        document=export.content,
        filename=export.filename,
        caption=caption,
        reply_markup=await main_menu_keyboard(telegram_id),
    )
    return MAIN_MENU


@service_errors('Flag')
async def toggle_flag(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    telegram_id = update.effective_user.id
    entry = await asyncio.to_thread(deps.journal_svc.toggle_session_flag, telegram_id)

    if entry is None:
        await update.message.reply_text(
            FLAG_NO_ENTRY, parse_mode='Markdown', reply_markup=await main_menu_keyboard(telegram_id)
        )
        return MAIN_MENU

    flagged = entry['flagged_for_session']
    await asyncio.to_thread(deps.analytics_svc.track, analytics.SESSION_FLAG_TOGGLED, telegram_id, flagged=flagged)

    user = await asyncio.to_thread(deps.user_svc.get, telegram_id) or {}
    tz = resolve_timezone(user.get('timezone'), telegram_id)
    date = to_local(entry['created_at'], tz).strftime('%a %d %b')
    await update.message.reply_text(
        (FLAG_SET if flagged else FLAG_CLEARED).format(date=date),
        parse_mode='Markdown',
        reply_markup=await main_menu_keyboard(telegram_id),
    )
    return MAIN_MENU
