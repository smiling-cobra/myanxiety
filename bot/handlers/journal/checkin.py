"""The check-in flow: mood rating, entry text, LLM response, optional guidance offer.

Service calls go through `asyncio.to_thread` — see the package docstring.

Two guarantees hold this module together, and both are about what survives when
something else fails.

*Crisis resources are unconditional.* They are sent before any call that can
fail, on every path that reaches a scored entry, whether the trigger was the
mood score or the text itself. Nothing downstream of a `try` is a guarantee.

*The entry is saved even when the LLM is not called.* A user at their daily
Anthropic ceiling loses the written reflection, never the thing they wrote.

The first entry of the user's local day is the *daily check-in*: it carries the
streak and the written reflection. Any later entry that day is a *note* — the
same mood, text and safety path, acknowledged with a fixed line instead of a
reflection. There is no limit on notes: the moment someone most needs to write
is often the second time that day, and the crisis lexicon cannot read text that
was never written.
"""
import asyncio
import logging

from telegram import Update
from telegram.ext import ContextTypes

from bot.handlers.journal import deps
from bot.handlers.journal.states import (
    CHECK_IN_GUIDANCE_OFFER,
    CHECK_IN_MOOD,
    CHECK_IN_TEXT,
    CRISIS_MOOD_THRESHOLD,
    LOW_MOOD_THRESHOLD,
    MAIN_MENU,
)
from bot.keyboards import GUIDANCE_YES, get_guidance_keyboard, get_main_menu_keyboard, get_mood_keyboard
from messages.markdown import escape_md
from messages.strings import (
    CHECK_IN_DONE,
    CHECK_IN_DONE_BRIEF,
    CHECK_IN_TEXT_PROMPT,
    ERROR_GENERIC,
    GUIDANCE_CRISIS_RESOURCES,
    GUIDANCE_DECLINED,
    GUIDANCE_OFFER_LOW,
    GUIDANCE_OFFER_VERY_LOW,
    GUIDANCE_STATIC_FALLBACK,
    MOOD_LOST,
    NOTE_SAVED,
    WRONG_MOOD,
)
from services import analytics_service as analytics
from services.safety import detect_crisis

logger = logging.getLogger(__name__)

# One check-in spends two Anthropic calls: tag extraction and the reply. A note
# spends only the first, but whether an entry is a note is not known until it is
# saved, so both are reserved and the reply is handed back for a note.
_CHECK_IN_LLM_CALLS = 2

_DAILY = 'daily'
_NOTE = 'note'

_MOOD_TRIGGER = 'mood'
_CONTENT_TRIGGER = 'content'
_LOST_STATE_TRIGGER = 'lost_state'


def _name(context: ContextTypes.DEFAULT_TYPE) -> str:
    return context.user_data.get('name', 'there')


async def handle_mood(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text.strip()
    if not text.isdigit() or not (1 <= int(text) <= 10):
        await update.message.reply_text(WRONG_MOOD, reply_markup=get_mood_keyboard())
        return CHECK_IN_MOOD
    score = int(text)
    context.user_data['mood_score'] = score
    await asyncio.to_thread(
        deps.analytics_svc.track, analytics.CHECK_IN_STARTED, update.effective_user.id, mood_score=score
    )
    await update.message.reply_text(CHECK_IN_TEXT_PROMPT.format(score=text))
    return CHECK_IN_TEXT


def _crisis_triggers(mood_score: int, categories: tuple) -> list:
    """Which signals, if any, call for crisis resources on this entry.

    Two independent triggers, deliberately not collapsed into one score. A low
    rating with unremarkable text and a 7/10 rating with "I can't do this any
    more" are both reasons to show the numbers, and the second is the case an
    exact mood threshold has always missed. Both are recorded so their rates
    can be compared later.
    """
    triggers = []
    if mood_score <= CRISIS_MOOD_THRESHOLD:
        triggers.append(_MOOD_TRIGGER)
    if categories:
        triggers.append(_CONTENT_TRIGGER)
    return triggers


async def _send_crisis_resources(update: Update, telegram_id: int, triggers: list, categories=()) -> None:
    """Deliver crisis resources. Never gated on an opt-in, a DB call or an LLM call.

    The event records *why* they were shown — which trigger fired, and which
    lexicon categories matched — because the false-positive rate of the lexicon
    is otherwise unknowable, and it is the number that decides whether the
    wording of `GUIDANCE_OFFER_VERY_LOW` is doing more good than harm. It never
    records what the user wrote: the categories are a closed vocabulary from
    `services/safety.py`, not the user's own words.
    """
    await update.message.reply_text(GUIDANCE_CRISIS_RESOURCES, parse_mode='Markdown')
    await asyncio.to_thread(
        deps.analytics_svc.track,
        analytics.CRISIS_RESOURCES_SHOWN,
        telegram_id,
        triggers=triggers,
        categories=list(categories),
    )


async def _completion_message(
    telegram_id: int, name: str, first_of_day: bool, llm_response: str | None, streak: int
) -> str:
    """The reply to a saved entry: a note's acknowledgement, or the check-in with or without a reflection."""
    if not first_of_day:
        return NOTE_SAVED.format(name=escape_md(name))
    if llm_response is None:
        await asyncio.to_thread(
            deps.analytics_svc.track, analytics.LLM_BUDGET_EXCEEDED, telegram_id, surface='check_in'
        )
        return CHECK_IN_DONE_BRIEF.format(name=escape_md(name), streak=streak)
    return CHECK_IN_DONE.format(name=escape_md(name), llm_response=escape_md(llm_response), streak=streak)


async def handle_entry_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text.strip()
    telegram_id = update.effective_user.id
    mood_score = context.user_data.get('mood_score')
    name = _name(context)

    # Fail closed: without the score we cannot tell a 1 from a 9, and assuming
    # a middling default silently skips both the guidance offer and the crisis
    # path. Re-ask instead.
    if mood_score is None:
        logger.warning('handle_entry_text: mood_score missing for user %s', telegram_id)
        await update.message.reply_text(MOOD_LOST, reply_markup=get_mood_keyboard())
        return CHECK_IN_MOOD

    # Before the try block on purpose. Everything below can fail — a Mongo
    # blip, an Anthropic timeout — and the except returns to the main menu,
    # so anything downstream of it is not a guarantee.
    categories = detect_crisis(text)
    triggers = _crisis_triggers(mood_score, categories)
    if triggers:
        await _send_crisis_resources(update, telegram_id, triggers, categories)

    llm_allowed = await asyncio.to_thread(deps.usage_svc.consume_llm, telegram_id, _CHECK_IN_LLM_CALLS)

    try:
        tags = await asyncio.to_thread(deps.llm_svc.extract_tags, text) if llm_allowed else []
        first_of_day = await asyncio.to_thread(deps.journal_svc.save_entry, telegram_id, mood_score, text, tags)
        stats = await asyncio.to_thread(deps.journal_svc.get_stats, telegram_id)
        llm_response = (
            await asyncio.to_thread(deps.llm_svc.get_empathetic_response, mood_score, text)
            if llm_allowed and first_of_day else None
        )
    except Exception:
        logger.exception('Check-in failed for user %s', telegram_id)
        # Two calls were reserved; the save sits between them, so a database
        # failure here means the reply was never requested. Hand that one back —
        # otherwise a run of failures walks the user toward a ceiling on work
        # that never reached Anthropic. The tag call is not refunded: by this
        # point it has already been made.
        if llm_allowed:
            await asyncio.to_thread(deps.usage_svc.refund, telegram_id, 1)
        await asyncio.to_thread(
            deps.analytics_svc.track, analytics.CHECK_IN_FAILED, telegram_id, mood_score=mood_score
        )
        await update.message.reply_text(ERROR_GENERIC, reply_markup=get_main_menu_keyboard())
        return MAIN_MENU

    if not first_of_day and llm_allowed:
        # A note was never going to get a reply, so its reserved call is handed back.
        await asyncio.to_thread(deps.usage_svc.refund, telegram_id, 1)

    body = await _completion_message(telegram_id, name, first_of_day, llm_response, stats['streak'])
    # Whichever kind this was, the next entry today is a note.
    await update.message.reply_text(body, reply_markup=get_main_menu_keyboard(checked_in=True), parse_mode='Markdown')
    await asyncio.to_thread(
        deps.analytics_svc.track,
        analytics.CHECK_IN_COMPLETED,
        telegram_id,
        kind=_DAILY if first_of_day else _NOTE,
        mood_score=mood_score,
        text_length=len(text),
        tag_count=len(tags),
        streak=stats['streak'],
        llm=llm_response is not None,
    )

    # A content match opens the guidance offer even when the rating is high,
    # for the same reason it shows the resources: the text is the signal the
    # number missed.
    acute = mood_score <= CRISIS_MOOD_THRESHOLD or bool(categories)
    if acute or mood_score <= LOW_MOOD_THRESHOLD:
        context.user_data['entry_text'] = text
        context.user_data['acute'] = acute
        offer = GUIDANCE_OFFER_VERY_LOW if acute else GUIDANCE_OFFER_LOW
        await update.message.reply_text(offer, reply_markup=get_guidance_keyboard())
        await asyncio.to_thread(
            deps.analytics_svc.track,
            analytics.GUIDANCE_OFFERED,
            telegram_id,
            mood_score=mood_score,
            acute=acute,
        )
        return CHECK_IN_GUIDANCE_OFFER

    return MAIN_MENU


async def handle_guidance_offer(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    telegram_id = update.effective_user.id
    mood_score = context.user_data.get('mood_score')

    # This state is only reachable from a low-mood or content-flagged check-in,
    # so a missing score means lost state, not a well user. Fail closed and show
    # resources.
    if mood_score is None:
        logger.warning('handle_guidance_offer: mood_score missing for user %s', telegram_id)
        await _send_crisis_resources(update, telegram_id, [_LOST_STATE_TRIGGER])
        mood_score = CRISIS_MOOD_THRESHOLD

    if update.message.text != GUIDANCE_YES:
        await asyncio.to_thread(deps.analytics_svc.track, analytics.GUIDANCE_DECLINED, telegram_id)
        await update.message.reply_text(GUIDANCE_DECLINED, reply_markup=get_main_menu_keyboard(checked_in=True))
        return MAIN_MENU

    entry_text = context.user_data.get('entry_text', '')
    if not entry_text:
        logger.warning('handle_guidance_offer: entry_text missing for user %s', telegram_id)

    await asyncio.to_thread(deps.analytics_svc.track, analytics.GUIDANCE_ACCEPTED, telegram_id)

    # `acute` is not on the persistence allowlist, so a restart between the offer
    # and the answer drops it and a high-rated user gets the non-crisis technique
    # set. The hotline numbers were already sent unconditionally, so the cost of
    # that is the flavour of the advice, not the safety of it.
    severity = min(mood_score, CRISIS_MOOD_THRESHOLD) if context.user_data.get('acute') else mood_score

    if await asyncio.to_thread(deps.usage_svc.consume_llm, telegram_id, 1):
        guidance = await asyncio.to_thread(deps.llm_svc.get_psychological_guidance, severity, entry_text)
    else:
        # Someone who just asked for help gets a real exercise, not an apology.
        await asyncio.to_thread(
            deps.analytics_svc.track, analytics.LLM_BUDGET_EXCEEDED, telegram_id, surface='guidance'
        )
        guidance = GUIDANCE_STATIC_FALLBACK

    await update.message.reply_text(guidance, reply_markup=get_main_menu_keyboard(checked_in=True))
    return MAIN_MENU
