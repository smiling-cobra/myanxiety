import logging
import re
from collections import Counter
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError, available_timezones

from telegram import ReplyKeyboardMarkup, ReplyKeyboardRemove, Update
from telegram.ext import (
    CallbackContext,
    CommandHandler,
    ConversationHandler,
    Filters,
    MessageHandler,
)
from timezonefinder import TimezoneFinder

from bot.keyboards import (
    CHECK_IN, HELP, HISTORY, STATS,
    get_main_menu_keyboard, get_mood_keyboard, get_timezone_keyboard,
)
from messages.strings import (
    CANCEL_MESSAGE,
    CHECK_IN_DONE,
    CHECK_IN_MOOD_PROMPT,
    CHECK_IN_TEXT_PROMPT,
    HELP_MESSAGE,
    HISTORY_EMPTY,
    HISTORY_ENTRY,
    HISTORY_HEADER,
    MAIN_MENU_MESSAGE,
    ONBOARDING_DONE,
    ONBOARDING_TIME as ONBOARDING_TIME_MSG,
    ONBOARDING_TIMEZONE as ONBOARDING_TIMEZONE_MSG,
    ONBOARDING_WELCOME,
    STATS_EMPTY,
    STATS_MESSAGE,
    TIMEZONE_DETECTED,
    TIMEZONE_DETECTION_FAILED,
    TIMEZONE_SUGGESTIONS,
    WRONG_MOOD,
    WRONG_TIME,
    WRONG_TIMEZONE,
)
from services.journal_service import JournalService
from services.llm_service import LlmService
from services.user_service import UserService

logger = logging.getLogger(__name__)
_tf = TimezoneFinder()
_ALL_TIMEZONES = sorted(available_timezones())


def _search_timezones(query: str) -> list:
    """Return IANA timezone names that contain the query (case-insensitive, spaces→underscores)."""
    needle = query.strip().replace(' ', '_').lower()
    return [tz for tz in _ALL_TIMEZONES if needle in tz.lower()]

ONBOARDING_NAME, ONBOARDING_TIMEZONE, ONBOARDING_TIME, MAIN_MENU, CHECK_IN_MOOD, CHECK_IN_TEXT = range(6)


def _escape_md(text: str) -> str:
    """Escape Markdown v1 special characters in user-supplied or external text."""
    for char in ('*', '_', '`', '['):
        text = text.replace(char, f'\\{char}')
    return text

_user_svc = UserService()
_journal_svc = JournalService()
_llm_svc = LlmService()


def _name(context: CallbackContext) -> str:
    return context.user_data.get('name', 'there')


def start(update: Update, context: CallbackContext) -> int:
    telegram_id = update.effective_user.id
    user = _user_svc.get(telegram_id)
    if user and user.get('onboarded'):
        context.user_data['name'] = user['name']
        update.message.reply_text(
            MAIN_MENU_MESSAGE.format(name=user['name']),
            reply_markup=get_main_menu_keyboard()
        )
        return MAIN_MENU
    update.message.reply_text(ONBOARDING_WELCOME)
    return ONBOARDING_NAME


def handle_name(update: Update, context: CallbackContext) -> int:
    name = update.message.text.strip()
    context.user_data['name'] = name
    update.message.reply_text(
        ONBOARDING_TIMEZONE_MSG.format(name=name),
        reply_markup=get_timezone_keyboard(),
    )
    return ONBOARDING_TIMEZONE


def handle_timezone_location(update: Update, context: CallbackContext) -> int:
    loc = update.message.location
    tz_str = _tf.timezone_at(lat=loc.latitude, lng=loc.longitude)
    if not tz_str:
        update.message.reply_text(TIMEZONE_DETECTION_FAILED, reply_markup=get_timezone_keyboard())
        return ONBOARDING_TIMEZONE
    context.user_data['timezone'] = tz_str
    update.message.reply_text(
        TIMEZONE_DETECTED.format(timezone=tz_str),
        parse_mode='Markdown',
        reply_markup=get_timezone_keyboard(),
    )
    update.message.reply_text(ONBOARDING_TIME_MSG)
    return ONBOARDING_TIME


def handle_timezone(update: Update, context: CallbackContext) -> int:
    tz_str = update.message.text.strip()

    # Exact IANA match
    try:
        ZoneInfo(tz_str)
        context.user_data['timezone'] = tz_str
        update.message.reply_text(ONBOARDING_TIME_MSG)
        return ONBOARDING_TIME
    except (ZoneInfoNotFoundError, KeyError):
        pass

    # Fuzzy substring search
    matches = _search_timezones(tz_str)
    if len(matches) == 1:
        context.user_data['timezone'] = matches[0]
        update.message.reply_text(
            TIMEZONE_DETECTED.format(timezone=matches[0]),
            parse_mode='Markdown',
        )
        update.message.reply_text(ONBOARDING_TIME_MSG)
        return ONBOARDING_TIME
    if 1 < len(matches) <= 5:
        kb = ReplyKeyboardMarkup([[m] for m in matches], resize_keyboard=True, one_time_keyboard=True)
        update.message.reply_text(TIMEZONE_SUGGESTIONS.format(query=tz_str), reply_markup=kb)
        return ONBOARDING_TIMEZONE

    update.message.reply_text(WRONG_TIMEZONE)
    return ONBOARDING_TIMEZONE


def handle_reminder_time(update: Update, context: CallbackContext) -> int:
    time_str = update.message.text.strip()
    if not re.match(r'^\d{2}:\d{2}$', time_str):
        update.message.reply_text(WRONG_TIME)
        return ONBOARDING_TIME
    h, m = int(time_str[:2]), int(time_str[3:])
    if not (0 <= h <= 23 and 0 <= m <= 59):
        update.message.reply_text(WRONG_TIME)
        return ONBOARDING_TIME

    name = context.user_data['name']
    timezone = context.user_data['timezone']
    _user_svc.create_or_update(
        update.effective_user.id,
        name=name,
        timezone=timezone,
        reminder_time=time_str,
        onboarded=True,
    )
    update.message.reply_text(
        ONBOARDING_DONE.format(name=name, reminder_time=time_str, timezone=timezone),
        reply_markup=get_main_menu_keyboard(),
        parse_mode='Markdown',
    )
    return MAIN_MENU


def handle_main_menu(update: Update, context: CallbackContext) -> int:
    choice = update.message.text
    name = _name(context)

    if choice == CHECK_IN:
        update.message.reply_text(
            CHECK_IN_MOOD_PROMPT.format(name=name),
            reply_markup=get_mood_keyboard()
        )
        return CHECK_IN_MOOD

    if choice == HISTORY:
        return _show_history(update, context)

    if choice == STATS:
        return _show_stats(update, context)

    if choice == HELP:
        update.message.reply_text(HELP_MESSAGE, parse_mode='Markdown')
        return MAIN_MENU

    return MAIN_MENU


def handle_mood(update: Update, context: CallbackContext) -> int:
    text = update.message.text.strip()
    if not text.isdigit() or not (1 <= int(text) <= 10):
        update.message.reply_text(WRONG_MOOD, reply_markup=get_mood_keyboard())
        return CHECK_IN_MOOD
    context.user_data['mood_score'] = int(text)
    update.message.reply_text(CHECK_IN_TEXT_PROMPT.format(score=text))
    return CHECK_IN_TEXT


def handle_entry_text(update: Update, context: CallbackContext) -> int:
    text = update.message.text.strip()
    telegram_id = update.effective_user.id
    mood_score = context.user_data.get('mood_score', 5)
    name = _name(context)

    tags = _llm_svc.extract_tags(text)
    _journal_svc.save_entry(telegram_id, mood_score, text, tags)

    stats = _journal_svc.get_stats(telegram_id)
    llm_response = _llm_svc.get_empathetic_response(mood_score, text)

    update.message.reply_text(
        CHECK_IN_DONE.format(name=_escape_md(name), llm_response=_escape_md(llm_response), streak=stats['streak']),
        reply_markup=get_main_menu_keyboard(),
        parse_mode='Markdown',
    )
    return MAIN_MENU


def _show_history(update: Update, context: CallbackContext) -> int:
    telegram_id = update.effective_user.id
    entries = _journal_svc.get_recent_entries(telegram_id)
    if not entries:
        update.message.reply_text(
            HISTORY_EMPTY, parse_mode='Markdown', reply_markup=get_main_menu_keyboard()
        )
        return MAIN_MENU

    body = HISTORY_HEADER.format(count=len(entries))
    for e in entries:
        date_str = e['created_at'].strftime('%d %b %Y')
        body += HISTORY_ENTRY.format(date=date_str, score=e['mood_score'], text=_escape_md(e['text'][:200]))

    update.message.reply_text(body, parse_mode='Markdown', reply_markup=get_main_menu_keyboard())
    return MAIN_MENU


def _show_stats(update: Update, context: CallbackContext) -> int:
    telegram_id = update.effective_user.id
    stats = _journal_svc.get_stats(telegram_id)
    if stats['total'] == 0:
        update.message.reply_text(STATS_EMPTY, reply_markup=get_main_menu_keyboard())
        return MAIN_MENU

    entries = _journal_svc.get_recent_entries(telegram_id, 7)
    all_tags = [tag for e in entries for tag in e.get('tags', [])]
    top_tags = ', '.join(f'#{t}' for t, _ in Counter(all_tags).most_common(3)) or 'none yet'

    update.message.reply_text(
        STATS_MESSAGE.format(
            streak=stats['streak'],
            total=stats['total'],
            avg_mood=stats['avg_mood'],
            tags=top_tags,
        ),
        parse_mode='Markdown',
        reply_markup=get_main_menu_keyboard(),
    )
    return MAIN_MENU


def cancel(update: Update, context: CallbackContext) -> int:
    update.message.reply_text(
        CANCEL_MESSAGE.format(name=_name(context)),
        reply_markup=ReplyKeyboardRemove(),
    )
    return ConversationHandler.END


def register(dispatcher) -> None:
    handler = ConversationHandler(
        entry_points=[CommandHandler('start', start)],
        states={
            ONBOARDING_NAME: [MessageHandler(Filters.text & ~Filters.command, handle_name)],
            ONBOARDING_TIMEZONE: [
                MessageHandler(Filters.location, handle_timezone_location),
                MessageHandler(Filters.text & ~Filters.command, handle_timezone),
            ],
            ONBOARDING_TIME: [MessageHandler(Filters.text & ~Filters.command, handle_reminder_time)],
            MAIN_MENU: [MessageHandler(Filters.text & ~Filters.command, handle_main_menu)],
            CHECK_IN_MOOD: [MessageHandler(Filters.text & ~Filters.command, handle_mood)],
            CHECK_IN_TEXT: [MessageHandler(Filters.text & ~Filters.command, handle_entry_text)],
        },
        fallbacks=[CommandHandler('cancel', cancel)],
    )
    dispatcher.add_handler(handler)
