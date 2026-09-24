"""/settings — change the reminder time, pause reminders, resume them early.

Service calls go through `asyncio.to_thread` — see the package docstring.

Reminders can be paused but never switched off. A pause is stored as
`reminders_paused_until`, the local date reminders resume, and the scheduler
simply treats the user as not due before it (`SchedulerService._reminders_paused`).
Nothing has to run for a pause to end, and `reminder_time` is untouched, so the
reminders come back at the time they had. Only the daily reminder pauses; the
weekly summary keeps its own cadence.

The writes use the non-upserting `UserService.update`: these are changes to an
account that must already exist, and a stale settings keyboard tapped after
/delete must not recreate one.

A changed reminder time needs no watermark handling here. `last_reminder_sent`
is a local date, so a user already reminded today is not reminded again at the
new time, and one who hasn't been is reminded when the new time comes round.
"""
import asyncio
from datetime import date, timedelta

from telegram import Update
from telegram.ext import ContextTypes

from bot.handlers.journal import deps
from bot.handlers.journal.errors import service_errors
from bot.handlers.journal.main_menu import main_menu_keyboard
from bot.handlers.journal.states import MAIN_MENU, SETTINGS_MENU, SETTINGS_PAUSE_LENGTH, SETTINGS_TIME
from bot.keyboards import (
    BACK,
    CHANGE_REMINDER_TIME,
    PAUSE_LENGTHS,
    PAUSE_REMINDERS,
    RESUME_REMINDERS,
    get_back_keyboard,
    get_pause_keyboard,
    get_settings_keyboard,
)
from messages.markdown import escape_md
from messages.strings import (
    MAIN_MENU_MESSAGE,
    PAUSE_PROMPT,
    REMINDER_TIME_CHANGED,
    REMINDER_TIME_CHANGED_WHILE_PAUSED,
    REMINDERS_PAUSED,
    REMINDERS_RESUMED,
    SETTINGS_NOT_READY,
    SETTINGS_OVERVIEW,
    SETTINGS_STATUS_ACTIVE,
    SETTINGS_STATUS_PAUSED,
    SETTINGS_TIME_PROMPT,
    WRONG_TIME,
)
from services import analytics_service as analytics
from services.time_utils import local_today, parse_reminder_time


def pause_end(user: dict) -> date | None:
    """The date a running pause ends, or None if reminders are on.

    The same rule as the scheduler's: paused while the local date is before
    `reminders_paused_until`. A pause that has run out reads as no pause.
    """
    raw = user.get('reminders_paused_until')
    if not raw:
        return None
    try:
        until = date.fromisoformat(raw)
    except (TypeError, ValueError):
        return None
    return until if local_today(user.get('timezone'), user.get('telegram_id')) < until else None


def _day_label(day: date) -> str:
    return f'{day:%A} {day.day} {day:%B}'


async def _get_user(telegram_id: int) -> dict:
    return await asyncio.to_thread(deps.user_svc.get, telegram_id) or {}


@service_errors('Settings')
async def show_settings(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int | None:
    telegram_id = update.effective_user.id
    user = await _get_user(telegram_id)
    if not user.get('onboarded'):
        # Before the reminder-time step there is nothing to configure yet, and
        # returning None leaves the conversation on the step it was at. From the
        # optional cohort question on, the account is complete (`onboarded` is
        # written with the reminder time), so settings open like any other
        # command there, and the question is left unanswered as /history would.
        await update.message.reply_text(SETTINGS_NOT_READY)
        return None

    await asyncio.to_thread(deps.analytics_svc.track, analytics.SETTINGS_VIEWED, telegram_id)
    return await _show_overview(update, user)


async def _show_overview(update: Update, user: dict) -> int:
    paused_until = pause_end(user)
    status = (
        SETTINGS_STATUS_PAUSED.format(date=_day_label(paused_until)) if paused_until
        else SETTINGS_STATUS_ACTIVE
    )
    await update.message.reply_text(
        SETTINGS_OVERVIEW.format(
            reminder_time=user.get('reminder_time', '—'),
            timezone=escape_md(user.get('timezone', '')),
            status=status,
        ),
        parse_mode='Markdown',
        reply_markup=get_settings_keyboard(paused=paused_until is not None),
    )
    return SETTINGS_MENU


async def _back_to_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str) -> int:
    await update.message.reply_text(
        text,
        parse_mode='Markdown',
        reply_markup=await main_menu_keyboard(update.effective_user.id),
    )
    return MAIN_MENU


@service_errors('Settings')
async def handle_settings_choice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    choice = update.message.text
    telegram_id = update.effective_user.id
    user = await _get_user(telegram_id)

    if choice == CHANGE_REMINDER_TIME:
        await update.message.reply_text(
            SETTINGS_TIME_PROMPT.format(reminder_time=user.get('reminder_time', '—')),
            reply_markup=get_back_keyboard(),
        )
        return SETTINGS_TIME

    if choice == PAUSE_REMINDERS:
        await update.message.reply_text(PAUSE_PROMPT, reply_markup=get_pause_keyboard())
        return SETTINGS_PAUSE_LENGTH

    if choice == RESUME_REMINDERS and pause_end(user):
        await asyncio.to_thread(deps.user_svc.update, telegram_id, reminders_paused_until=None)
        await asyncio.to_thread(deps.analytics_svc.track, analytics.REMINDERS_RESUMED, telegram_id)
        return await _back_to_main_menu(
            update, context, REMINDERS_RESUMED.format(reminder_time=user.get('reminder_time', '—'))
        )

    if choice == BACK:
        name = user.get('name') or context.user_data.get('name', 'there')
        return await _back_to_main_menu(update, context, MAIN_MENU_MESSAGE.format(name=escape_md(name)))

    # Anything else — typed text, or "Resume" on a pause that has already run
    # out — gets the current settings again, which is always an honest answer.
    return await _show_overview(update, user)


@service_errors('Settings')
async def handle_settings_time(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    telegram_id = update.effective_user.id
    if update.message.text == BACK:
        return await _show_overview(update, await _get_user(telegram_id))

    time_str = parse_reminder_time(update.message.text)
    if time_str is None:
        await update.message.reply_text(WRONG_TIME, reply_markup=get_back_keyboard())
        return SETTINGS_TIME

    await asyncio.to_thread(deps.user_svc.update, telegram_id, reminder_time=time_str)
    await asyncio.to_thread(
        deps.analytics_svc.track, analytics.REMINDER_TIME_CHANGED, telegram_id, hour=int(time_str[:2])
    )

    text = REMINDER_TIME_CHANGED.format(reminder_time=time_str)
    paused_until = pause_end(await _get_user(telegram_id))
    if paused_until:
        text += REMINDER_TIME_CHANGED_WHILE_PAUSED.format(date=_day_label(paused_until))
    return await _back_to_main_menu(update, context, text)


@service_errors('Settings')
async def handle_pause_length(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    telegram_id = update.effective_user.id
    user = await _get_user(telegram_id)
    if update.message.text == BACK:
        return await _show_overview(update, user)

    days = PAUSE_LENGTHS.get(update.message.text)
    if days is None:
        await update.message.reply_text(PAUSE_PROMPT, reply_markup=get_pause_keyboard())
        return SETTINGS_PAUSE_LENGTH

    # Counted from the user's own today, which the scheduler compares against in
    # the same terms: "3 days" skips today and the next two days, and the
    # reminder comes back three days from today.
    until = local_today(user.get('timezone'), telegram_id) + timedelta(days=days)
    await asyncio.to_thread(deps.user_svc.update, telegram_id, reminders_paused_until=until.isoformat())
    await asyncio.to_thread(deps.analytics_svc.track, analytics.REMINDERS_PAUSED, telegram_id, days=days)
    return await _back_to_main_menu(update, context, REMINDERS_PAUSED.format(date=_day_label(until)))
