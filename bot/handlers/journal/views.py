"""Read-only views: history, stats, weekly summary.

Service calls go through `asyncio.to_thread` — see the package docstring.
"""
from __future__ import annotations

import asyncio
from datetime import tzinfo

from telegram import Update
from telegram.ext import ContextTypes

from bot.handlers.journal import deps
from bot.handlers.journal.errors import service_errors
from bot.handlers.journal.states import MAIN_MENU
from bot.handlers.journal.main_menu import main_menu_keyboard
from messages.markdown import escape_md
from messages.strings import (
    HISTORY_EMPTY,
    HISTORY_ENTRY,
    HISTORY_HEADER,
    STATS_EMPTY,
    STATS_MESSAGE,
    WEEKLY_SUMMARY_EMPTY,
    WEEKLY_SUMMARY_HEADER,
    WEEKLY_SUMMARY_LLM_INTRO,
    WEEKLY_SUMMARY_TAGS,
    WEEKLY_SUMMARY_BUDGET_REACHED,
    WEEKLY_SUMMARY_TOO_FEW,
    WEEKLY_SUMMARY_TREND_ROW,
)
from services import analytics_service as analytics
from services.journal_service import MIN_ENTRIES_FOR_WEEKLY_SUMMARY
from services.tags import top_tags
from services.time_utils import resolve_timezone, to_local


def mood_bar(score: int) -> str:
    n = max(0, min(10, score))
    return '▓' * n + '░' * (10 - n)


def _format_tags(tags: list) -> str:
    return ', '.join(f'#{escape_md(t)}' for t in tags) or 'none yet'


async def _user_timezone(telegram_id: int) -> tuple[str | None, tzinfo]:
    """The user's stored IANA name (if any) and the resolved tzinfo."""
    user = await asyncio.to_thread(deps.user_svc.get, telegram_id) or {}
    name = user.get('timezone')
    return name, resolve_timezone(name, telegram_id)


@service_errors('History')
async def show_history(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    telegram_id = update.effective_user.id
    entries = await asyncio.to_thread(deps.journal_svc.get_recent_entries, telegram_id)
    _, tz = await _user_timezone(telegram_id)

    # Tracked before the empty-state return: someone who opens their history and
    # finds nothing is the most interesting reader of it, and an event that only
    # fires when there is something to show would never record them.
    await asyncio.to_thread(
        deps.analytics_svc.track, analytics.HISTORY_VIEWED, telegram_id, count=len(entries)
    )

    if not entries:
        await update.message.reply_text(
            HISTORY_EMPTY, parse_mode='Markdown', reply_markup=await main_menu_keyboard(telegram_id)
        )
        return MAIN_MENU

    body = HISTORY_HEADER.format(count=len(entries))
    for e in entries:
        date_str = to_local(e['created_at'], tz).strftime('%d %b %Y')
        body += HISTORY_ENTRY.format(date=date_str, score=e['mood_score'], text=escape_md(e['text'][:200]))

    await update.message.reply_text(body, parse_mode='Markdown', reply_markup=await main_menu_keyboard(telegram_id))
    return MAIN_MENU


@service_errors('Stats')
async def show_stats(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    telegram_id = update.effective_user.id
    stats = await asyncio.to_thread(deps.journal_svc.get_stats, telegram_id)
    entries = await asyncio.to_thread(deps.journal_svc.get_recent_entries, telegram_id, 7)

    await asyncio.to_thread(
        deps.analytics_svc.track,
        analytics.STATS_VIEWED,
        telegram_id,
        total=stats['total'],
        streak=stats['streak'],
    )

    if stats['total'] == 0:
        await update.message.reply_text(STATS_EMPTY, reply_markup=await main_menu_keyboard(telegram_id))
        return MAIN_MENU

    tags = _format_tags(top_tags(entries, 3))

    await update.message.reply_text(
        STATS_MESSAGE.format(
            streak=stats['streak'],
            total=stats['total'],
            avg_mood=stats['avg_mood'],
            tags=tags,
        ),
        parse_mode='Markdown',
        reply_markup=await main_menu_keyboard(telegram_id),
    )
    return MAIN_MENU


@service_errors('Weekly summary')
async def show_weekly_summary(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    telegram_id = update.effective_user.id
    name, tz = await _user_timezone(telegram_id)
    entries = await asyncio.to_thread(deps.journal_svc.get_weekly_entries, telegram_id, name)
    await asyncio.to_thread(
        deps.analytics_svc.track, analytics.WEEKLY_SUMMARY_VIEWED, telegram_id, entry_count=len(entries)
    )

    if not entries:
        await update.message.reply_text(
            WEEKLY_SUMMARY_EMPTY, parse_mode='Markdown', reply_markup=await main_menu_keyboard(telegram_id)
        )
        return MAIN_MENU

    date_from = to_local(entries[0]['created_at'], tz).strftime('%d %b')
    date_to = to_local(entries[-1]['created_at'], tz).strftime('%d %b')
    body = WEEKLY_SUMMARY_HEADER.format(date_from=date_from, date_to=date_to, count=len(entries))

    for e in entries:
        body += WEEKLY_SUMMARY_TREND_ROW.format(
            score=e['mood_score'],
            bar=mood_bar(e['mood_score']),
            day=to_local(e['created_at'], tz).strftime('%a %d %b'),
        )

    body += WEEKLY_SUMMARY_TAGS.format(tags=_format_tags(top_tags(entries, 5)))

    body += await _pattern_paragraph(telegram_id, name, entries)

    await update.message.reply_text(body, parse_mode='Markdown', reply_markup=await main_menu_keyboard(telegram_id))
    return MAIN_MENU


async def _pattern_paragraph(telegram_id: int, timezone_name: str | None, entries: list) -> str:
    """The LLM tail of the weekly summary, or an explanation of its absence.

    The trend rows and tag counts above it are computed locally and always
    render. Only this paragraph costs an Anthropic call, so it is the only part
    a thin week or an exhausted budget can remove — the user still gets their
    week either way.
    """
    if len(entries) < MIN_ENTRIES_FOR_WEEKLY_SUMMARY:
        return WEEKLY_SUMMARY_TOO_FEW

    if not await asyncio.to_thread(deps.usage_svc.consume_llm, telegram_id, 1, timezone_name):
        await asyncio.to_thread(
            deps.analytics_svc.track,
            analytics.LLM_BUDGET_EXCEEDED,
            telegram_id,
            surface='weekly_summary_view',
        )
        return WEEKLY_SUMMARY_BUDGET_REACHED

    summary = await asyncio.to_thread(deps.llm_svc.get_weekly_summary, entries)
    return WEEKLY_SUMMARY_LLM_INTRO + escape_md(summary)
