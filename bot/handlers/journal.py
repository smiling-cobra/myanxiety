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
    CHECK_IN, GUIDANCE_NO, GUIDANCE_YES, HELP, HISTORY, STATS, WEEKLY_SUMMARY,
    get_guidance_keyboard, get_main_menu_keyboard, get_mood_keyboard, get_timezone_keyboard,
)
from messages.strings import (
    CANCEL_MESSAGE,
    CHECK_IN_DONE,
    CHECK_IN_MOOD_PROMPT,
    CHECK_IN_TEXT_PROMPT,
    ERROR_GENERIC,
    GUIDANCE_CRISIS_RESOURCES,
    GUIDANCE_DECLINED,
    GUIDANCE_ERROR_MESSAGE,
    GUIDANCE_OFFER_LOW,
    GUIDANCE_OFFER_VERY_LOW,
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
    WEEKLY_SUMMARY_EMPTY,
    WEEKLY_SUMMARY_HEADER,
    WEEKLY_SUMMARY_LLM_INTRO,
    WEEKLY_SUMMARY_TAGS,
    WEEKLY_SUMMARY_TOO_FEW,
    WEEKLY_SUMMARY_TREND_ROW,
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

_MD_SPECIAL = re.compile(r'([_*`\[])')


def _escape_md(text: str) -> str:
    return _MD_SPECIAL.sub(r'\\\1', text)
_tf = TimezoneFinder()
_ALL_TIMEZONES = sorted(available_timezones())


def _search_timezones(query: str) -> list:
    """Return IANA timezone names that contain the query (case-insensitive, spaces→underscores)."""
    needle = query.strip().replace(' ', '_').lower()
    return [tz for tz in _ALL_TIMEZONES if needle in tz.lower()]

ONBOARDING_NAME, ONBOARDING_TIMEZONE, ONBOARDING_TIME, MAIN_MENU, CHECK_IN_MOOD, CHECK_IN_TEXT, CHECK_IN_GUIDANCE_OFFER = range(7)

LOW_MOOD_THRESHOLD = 4


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
        TIMEZONE_DETECTED.format(timezone=_escape_md(tz_str)),
        parse_mode='Markdown',
        reply_markup=get_timezone_keyboard(),
    )
    update.message.reply_text(ONBOARDING_TIME_MSG, reply_markup=ReplyKeyboardRemove())
    return ONBOARDING_TIME


def handle_timezone(update: Update, context: CallbackContext) -> int:
    tz_str = update.message.text.strip()

    # Exact IANA match
    try:
        ZoneInfo(tz_str)
        context.user_data['timezone'] = tz_str
        update.message.reply_text(ONBOARDING_TIME_MSG, reply_markup=ReplyKeyboardRemove())
        return ONBOARDING_TIME
    except (ZoneInfoNotFoundError, KeyError):
        pass

    # Fuzzy substring search
    matches = _search_timezones(tz_str)
    if len(matches) == 1:
        context.user_data['timezone'] = matches[0]
        update.message.reply_text(
            TIMEZONE_DETECTED.format(timezone=_escape_md(matches[0])),
            parse_mode='Markdown',
        )
        update.message.reply_text(ONBOARDING_TIME_MSG, reply_markup=ReplyKeyboardRemove())
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
        ONBOARDING_DONE.format(name=_escape_md(name), reminder_time=time_str, timezone=timezone),
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
        return show_history(update, context)

    if choice == STATS:
        return show_stats(update, context)

    if choice == WEEKLY_SUMMARY:
        return show_weekly_summary(update, context)

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

    try:
        tags = _llm_svc.extract_tags(text)
        _journal_svc.save_entry(telegram_id, mood_score, text, tags)
        stats = _journal_svc.get_stats(telegram_id)
        llm_response = _llm_svc.get_empathetic_response(mood_score, text)
    except Exception:
        logger.exception('Check-in failed for user %s', telegram_id)
        update.message.reply_text(ERROR_GENERIC, reply_markup=get_main_menu_keyboard())
        return MAIN_MENU

    update.message.reply_text(
        CHECK_IN_DONE.format(name=_escape_md(name), llm_response=_escape_md(llm_response), streak=stats['streak']),
        reply_markup=get_main_menu_keyboard(),
        parse_mode='Markdown',
    )

    if mood_score <= LOW_MOOD_THRESHOLD:
        context.user_data['entry_text'] = text
        offer = GUIDANCE_OFFER_VERY_LOW if mood_score <= 2 else GUIDANCE_OFFER_LOW
        update.message.reply_text(offer, reply_markup=get_guidance_keyboard())
        return CHECK_IN_GUIDANCE_OFFER

    return MAIN_MENU


def show_history(update: Update, context: CallbackContext) -> int:
    telegram_id = update.effective_user.id
    try:
        entries = _journal_svc.get_recent_entries(telegram_id)
    except Exception:
        logger.exception('Failed to load history for user %s', telegram_id)
        update.message.reply_text(ERROR_GENERIC, reply_markup=get_main_menu_keyboard())
        return MAIN_MENU

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


def show_stats(update: Update, context: CallbackContext) -> int:
    telegram_id = update.effective_user.id
    try:
        stats = _journal_svc.get_stats(telegram_id)
        entries = _journal_svc.get_recent_entries(telegram_id, 7)
    except Exception:
        logger.exception('Failed to load stats for user %s', telegram_id)
        update.message.reply_text(ERROR_GENERIC, reply_markup=get_main_menu_keyboard())
        return MAIN_MENU

    if stats['total'] == 0:
        update.message.reply_text(STATS_EMPTY, reply_markup=get_main_menu_keyboard())
        return MAIN_MENU

    all_tags = [tag for e in entries for tag in e.get('tags', [])]
    top_tags = ', '.join(f'#{_escape_md(t)}' for t, _ in Counter(all_tags).most_common(3)) or 'none yet'

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


_MIN_ENTRIES_FOR_LLM_SUMMARY = 3


def _mood_bar(score: int) -> str:
    n = max(0, min(10, score))
    return '▓' * n + '░' * (10 - n)


def show_weekly_summary(update: Update, context: CallbackContext) -> int:
    telegram_id = update.effective_user.id
    try:
        entries = _journal_svc.get_weekly_entries(telegram_id)
    except Exception:
        logger.exception('Failed to load weekly entries for user %s', telegram_id)
        update.message.reply_text(ERROR_GENERIC, reply_markup=get_main_menu_keyboard())
        return MAIN_MENU

    if not entries:
        update.message.reply_text(
            WEEKLY_SUMMARY_EMPTY, parse_mode='Markdown', reply_markup=get_main_menu_keyboard()
        )
        return MAIN_MENU

    date_from = entries[0]['created_at'].strftime('%d %b')
    date_to = entries[-1]['created_at'].strftime('%d %b')
    body = WEEKLY_SUMMARY_HEADER.format(date_from=date_from, date_to=date_to, count=len(entries))

    for e in entries:
        body += WEEKLY_SUMMARY_TREND_ROW.format(
            score=e['mood_score'],
            bar=_mood_bar(e['mood_score']),
            day=e['created_at'].strftime('%a %d %b'),
        )

    all_tags = [tag for e in entries for tag in e.get('tags', [])]
    top_tags = ', '.join(f'#{_escape_md(t)}' for t, _ in Counter(all_tags).most_common(5)) or 'none yet'
    body += WEEKLY_SUMMARY_TAGS.format(tags=top_tags)

    if len(entries) >= _MIN_ENTRIES_FOR_LLM_SUMMARY:
        body += WEEKLY_SUMMARY_LLM_INTRO
        body += _escape_md(_llm_svc.get_weekly_summary(entries))
    else:
        body += WEEKLY_SUMMARY_TOO_FEW

    update.message.reply_text(body, parse_mode='Markdown', reply_markup=get_main_menu_keyboard())
    return MAIN_MENU


def handle_guidance_offer(update: Update, context: CallbackContext) -> int:
    if update.message.text != GUIDANCE_YES:
        update.message.reply_text(GUIDANCE_DECLINED, reply_markup=get_main_menu_keyboard())
        return MAIN_MENU

    mood_score = context.user_data.get('mood_score', 5)
    entry_text = context.user_data.get('entry_text', '')
    if not entry_text:
        logger.warning('handle_guidance_offer: entry_text missing for user %s', update.effective_user.id)

    guidance = _llm_svc.get_psychological_guidance(mood_score, entry_text)

    if mood_score <= 2:
        guidance = guidance + '\n\n' + GUIDANCE_CRISIS_RESOURCES

    update.message.reply_text(guidance, reply_markup=get_main_menu_keyboard())
    return MAIN_MENU


def cancel(update: Update, context: CallbackContext) -> int:
    update.message.reply_text(
        CANCEL_MESSAGE.format(name=_name(context)),
        reply_markup=ReplyKeyboardRemove(),
    )
    return ConversationHandler.END


def register(dispatcher) -> None:
    handler = ConversationHandler(
        entry_points=[
            CommandHandler('start', start),
            CommandHandler('history', show_history),
            CommandHandler('stats', show_stats),
            CommandHandler('summary', show_weekly_summary),
        ],
        states={
            ONBOARDING_NAME: [MessageHandler(Filters.text & ~Filters.command, handle_name)],
            ONBOARDING_TIMEZONE: [
                MessageHandler(Filters.location, handle_timezone_location),
                MessageHandler(Filters.text & ~Filters.command, handle_timezone),
            ],
            ONBOARDING_TIME: [MessageHandler(Filters.text & ~Filters.command, handle_reminder_time)],
            MAIN_MENU: [
                MessageHandler(Filters.text & ~Filters.command, handle_main_menu),
                CommandHandler('history', show_history),
                CommandHandler('stats', show_stats),
                CommandHandler('summary', show_weekly_summary),
            ],
            CHECK_IN_MOOD: [MessageHandler(Filters.text & ~Filters.command, handle_mood)],
            CHECK_IN_TEXT: [MessageHandler(Filters.text & ~Filters.command, handle_entry_text)],
            CHECK_IN_GUIDANCE_OFFER: [MessageHandler(Filters.text & ~Filters.command, handle_guidance_offer)],
        },
        fallbacks=[CommandHandler('cancel', cancel)],
        allow_reentry=True,
    )
    dispatcher.add_handler(handler)
