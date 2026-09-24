"""First-time setup: name, timezone, daily reminder time, cohort question.

Service calls go through `asyncio.to_thread` — see the package docstring.

Two cohort fields are captured here and nowhere else, because neither can be
reconstructed afterwards. `acquisition_source` comes from the `/start` deep-link
payload — `t.me/<bot>?start=reddit` arrives as `context.args` — which costs the
user nothing and beats asking them to recall where they found the bot.
`in_therapy` has to be asked, so it is one optional tap at the very end, after
the account already exists.
"""
import asyncio
import logging
import re
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from telegram import ReplyKeyboardMarkup, ReplyKeyboardRemove, Update
from telegram.ext import ContextTypes

from bot.handlers.journal import deps
from services import analytics_service as analytics
from services.time_utils import parse_reminder_time
from bot.handlers.journal.states import (
    MAIN_MENU,
    ONBOARDING_NAME,
    ONBOARDING_THERAPY,
    ONBOARDING_TIME,
    ONBOARDING_TIMEZONE,
)
from bot.handlers.journal.main_menu import main_menu_keyboard
from bot.handlers.journal.timezones import detect_timezone, search_timezones
from bot.keyboards import THERAPY_ANSWERS, get_main_menu_keyboard, get_therapy_keyboard, get_timezone_keyboard
from messages.markdown import escape_md
from messages.strings import (
    ONBOARDING_DONE,
    ONBOARDING_THERAPY as ONBOARDING_THERAPY_MSG,
    ONBOARDING_THERAPY_TIP,
    ONBOARDING_TIME as ONBOARDING_TIME_MSG,
    ONBOARDING_TIMEZONE as ONBOARDING_TIMEZONE_MSG,
    ONBOARDING_WELCOME,
    PRIVACY_ACCEPTED_PROMPT,
    PRIVACY_NOTICE,
    MAIN_MENU_MESSAGE,
    TIMEZONE_DETECTED,
    TIMEZONE_DETECTION_FAILED,
    TIMEZONE_SUGGESTIONS,
    WRONG_TIME,
    WRONG_TIMEZONE,
)

logger = logging.getLogger(__name__)

# A deep-link payload is whatever someone puts in a URL, so it is treated as
# untrusted input: anything that is not a short, plain campaign slug is
# discarded rather than stored. Telegram caps the payload at 64 characters and
# allows A-Z a-z 0-9 _ -; this is deliberately narrower.
_SOURCE_PATTERN = re.compile(r'^[a-z0-9_-]{1,32}$')
DIRECT_SOURCE = 'direct'


def _acquisition_source(context: ContextTypes.DEFAULT_TYPE) -> str:
    """The campaign slug from `/start <payload>`, or "direct"."""
    args = getattr(context, 'args', None)
    if not isinstance(args, (list, tuple)) or not args:
        return DIRECT_SOURCE
    candidate = str(args[0]).strip().lower()
    return candidate if _SOURCE_PATTERN.match(candidate) else DIRECT_SOURCE


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    telegram_id = update.effective_user.id
    user = await asyncio.to_thread(deps.user_svc.get, telegram_id)
    if user and user.get('onboarded'):
        context.user_data['name'] = user['name']
        await update.message.reply_text(
            MAIN_MENU_MESSAGE.format(name=user['name']),
            reply_markup=await main_menu_keyboard(telegram_id)
        )
        return MAIN_MENU

    # First touch wins, and it is written now rather than carried through three
    # more messages in `user_data`: a restart mid-onboarding is exactly what the
    # persistence layer exists for, and `acquisition_source` is not on its
    # allowlist. Writing it here creates the user document early, which is
    # harmless — `onboarded` is still absent, so the scheduler ignores it.
    source = _acquisition_source(context)
    if not (user or {}).get('acquisition_source'):
        await asyncio.to_thread(
            deps.user_svc.create_or_update, telegram_id, acquisition_source=source
        )
    await asyncio.to_thread(
        deps.analytics_svc.track, analytics.ONBOARDING_STARTED, telegram_id, source=source
    )

    await update.message.reply_text(ONBOARDING_WELCOME)
    await update.message.reply_text(PRIVACY_NOTICE, parse_mode='Markdown')
    await update.message.reply_text(PRIVACY_ACCEPTED_PROMPT)
    return ONBOARDING_NAME


async def handle_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    name = update.message.text.strip()
    context.user_data['name'] = name
    await update.message.reply_text(
        ONBOARDING_TIMEZONE_MSG.format(name=name),
        reply_markup=get_timezone_keyboard(),
    )
    return ONBOARDING_TIMEZONE


async def handle_timezone_location(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    loc = update.message.location
    tz_str = detect_timezone(loc.latitude, loc.longitude)
    if not tz_str:
        await update.message.reply_text(TIMEZONE_DETECTION_FAILED, reply_markup=get_timezone_keyboard())
        return ONBOARDING_TIMEZONE
    context.user_data['timezone'] = tz_str
    await update.message.reply_text(
        TIMEZONE_DETECTED.format(timezone=escape_md(tz_str)),
        parse_mode='Markdown',
        reply_markup=get_timezone_keyboard(),
    )
    await update.message.reply_text(ONBOARDING_TIME_MSG, reply_markup=ReplyKeyboardRemove())
    return ONBOARDING_TIME


async def handle_timezone(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    tz_str = update.message.text.strip()

    # Exact IANA match
    try:
        ZoneInfo(tz_str)
        context.user_data['timezone'] = tz_str
        await update.message.reply_text(ONBOARDING_TIME_MSG, reply_markup=ReplyKeyboardRemove())
        return ONBOARDING_TIME
    except (ZoneInfoNotFoundError, KeyError):
        pass

    # Fuzzy substring search
    matches = search_timezones(tz_str)
    if len(matches) == 1:
        context.user_data['timezone'] = matches[0]
        await update.message.reply_text(
            TIMEZONE_DETECTED.format(timezone=escape_md(matches[0])),
            parse_mode='Markdown',
        )
        await update.message.reply_text(ONBOARDING_TIME_MSG, reply_markup=ReplyKeyboardRemove())
        return ONBOARDING_TIME
    if 1 < len(matches) <= 5:
        kb = ReplyKeyboardMarkup([[m] for m in matches], resize_keyboard=True, one_time_keyboard=True)
        await update.message.reply_text(TIMEZONE_SUGGESTIONS.format(query=tz_str), reply_markup=kb)
        return ONBOARDING_TIMEZONE

    await update.message.reply_text(WRONG_TIMEZONE)
    return ONBOARDING_TIMEZONE


async def handle_reminder_time(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    time_str = parse_reminder_time(update.message.text)
    if time_str is None:
        await update.message.reply_text(WRONG_TIME)
        return ONBOARDING_TIME

    telegram_id = update.effective_user.id
    name = context.user_data['name']
    timezone = context.user_data['timezone']

    # The account is complete at this point and `onboarded` is set here, not
    # after the cohort question. Someone who abandons that optional last step is
    # a fully onboarded user with an unknown therapy status, not a half-created
    # one — and `recover_state` will put them back on the main menu.
    await asyncio.to_thread(
        deps.user_svc.create_or_update,
        telegram_id,
        name=name,
        timezone=timezone,
        reminder_time=time_str,
        onboarded=True,
    )
    await asyncio.to_thread(
        deps.analytics_svc.track, analytics.ONBOARDING_COMPLETED, telegram_id, timezone=timezone
    )

    await update.message.reply_text(ONBOARDING_THERAPY_MSG, reply_markup=get_therapy_keyboard())
    return ONBOARDING_THERAPY


async def handle_therapy(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Record the cohort answer, then close onboarding.

    Anything other than one of the three buttons is recorded as "undisclosed"
    rather than re-asked. This question is optional and last; trapping someone
    in a loop over it to satisfy a cohort field would be the wrong trade.
    """
    telegram_id = update.effective_user.id
    answer = THERAPY_ANSWERS.get(update.message.text.strip(), 'undisclosed')

    await asyncio.to_thread(deps.user_svc.create_or_update, telegram_id, in_therapy=answer)
    await asyncio.to_thread(
        deps.analytics_svc.track, analytics.COHORT_RECORDED, telegram_id, in_therapy=answer
    )

    # Read the account back rather than trusting `user_data` to have survived:
    # `timezone` and `reminder_time` are not on the persistence allowlist, and
    # this is the first step that runs after they were written to the database.
    user = await asyncio.to_thread(deps.user_svc.get, telegram_id) or {}
    name = user.get('name') or context.user_data.get('name', 'there')

    await update.message.reply_text(
        ONBOARDING_DONE.format(
            name=escape_md(name),
            reminder_time=user.get('reminder_time', ''),
            timezone=escape_md(user.get('timezone', '')),
            therapy_tip=ONBOARDING_THERAPY_TIP if answer == 'yes' else '',
        ),
        reply_markup=get_main_menu_keyboard(),
        parse_mode='Markdown',
    )
    return MAIN_MENU
