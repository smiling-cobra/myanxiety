"""Telegram conversation handlers for the daily check-in.

Everything here runs on the single asyncio event loop that python-telegram-bot
v20+ uses, so any blocking call — Anthropic over HTTP, pymongo over the wire —
would stall every other user for its duration. The services stay synchronous
(the scheduler calls them too), so each blocking call is handed to a worker
thread with `asyncio.to_thread` at the call site. That boundary is deliberate
and visible: if you add a service call here, wrap it.

This module is a thin orchestrator: it owns only the conversation state
machine and `register()`. Each responsibility lives in its own submodule:

    states.py       conversation-state ints and mood thresholds
    deps.py         service singletons — reach them as `deps.llm_svc`, etc.
    errors.py       @service_errors, the shared "fall back to main menu" decorator
    timezones.py    IANA timezone lookup (exact, fuzzy, and by coordinate)
    onboarding.py   name, timezone, reminder-time setup, cohort question
    menu.py         the main-menu router, /cancel, and lost-state recovery
    checkin.py      mood rating, entry text, LLM response, guidance offer
    views.py        history, stats, weekly summary
    export.py       /export — the therapist-shareable file, and /flag for it
    account.py      /delete — confirmation and the full fan-out
"""
from telegram.ext import Application, CommandHandler, ConversationHandler, MessageHandler, filters

from bot.handlers.journal.account import handle_delete_confirmation, request_delete
from bot.handlers.journal.checkin import handle_entry_text, handle_guidance_offer, handle_mood
from bot.handlers.journal.export import send_export, toggle_flag
from bot.handlers.journal.menu import cancel, handle_main_menu, recover_state
from bot.handlers.journal.onboarding import (
    handle_name,
    handle_reminder_time,
    handle_therapy,
    handle_timezone,
    handle_timezone_location,
    start,
)
from bot.handlers.journal.states import (
    CHECK_IN_GUIDANCE_OFFER,
    CHECK_IN_MOOD,
    CHECK_IN_TEXT,
    DELETE_CONFIRM,
    MAIN_MENU,
    ONBOARDING_NAME,
    ONBOARDING_THERAPY,
    ONBOARDING_TIME,
    ONBOARDING_TIMEZONE,
)
from bot.handlers.journal.views import show_history, show_stats, show_weekly_summary

__all__ = [
    'ONBOARDING_NAME',
    'ONBOARDING_TIMEZONE',
    'ONBOARDING_TIME',
    'ONBOARDING_THERAPY',
    'MAIN_MENU',
    'CHECK_IN_MOOD',
    'CHECK_IN_TEXT',
    'CHECK_IN_GUIDANCE_OFFER',
    'DELETE_CONFIRM',
    'start',
    'handle_name',
    'handle_timezone',
    'handle_timezone_location',
    'handle_reminder_time',
    'handle_therapy',
    'handle_main_menu',
    'handle_mood',
    'handle_entry_text',
    'handle_guidance_offer',
    'show_history',
    'show_stats',
    'show_weekly_summary',
    'send_export',
    'toggle_flag',
    'request_delete',
    'handle_delete_confirmation',
    'cancel',
    'recover_state',
    'register',
]


def register(application: Application) -> None:
    # Commands that work from anywhere — before the first conversation, and in
    # the middle of any state.
    commands = [
        CommandHandler('start', start),
        CommandHandler('history', show_history),
        CommandHandler('stats', show_stats),
        CommandHandler('summary', show_weekly_summary),
        CommandHandler('export', send_export),
        CommandHandler('flag', toggle_flag),
        CommandHandler('delete', request_delete),
    ]
    handler = ConversationHandler(
        entry_points=[
            *commands,
            # Last: only reached when nothing above matched and no conversation
            # is active, which is exactly the lost-state case.
            MessageHandler(filters.TEXT & ~filters.COMMAND, recover_state),
        ],
        states={
            ONBOARDING_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_name)],
            ONBOARDING_TIMEZONE: [
                MessageHandler(filters.LOCATION, handle_timezone_location),
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_timezone),
            ],
            ONBOARDING_TIME: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_reminder_time)],
            ONBOARDING_THERAPY: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_therapy)],
            MAIN_MENU: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_main_menu)],
            CHECK_IN_MOOD: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_mood)],
            CHECK_IN_TEXT: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_entry_text)],
            CHECK_IN_GUIDANCE_OFFER: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_guidance_offer)],
            DELETE_CONFIRM: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_delete_confirmation)],
        },
        # Commands reach an active conversation through the fallbacks, which are
        # consulted only after the current state's own handlers decline.
        #
        # They must not get there through `allow_reentry`. Re-entry checks the
        # entry points *before* the state handlers, and `recover_state` matches
        # any text — so with it on, every mood rating, journal entry and
        # onboarding answer was routed to recovery instead of to the step that
        # was waiting for it. tests/test_routing.py drives the real handler to
        # keep it that way.
        fallbacks=[*commands, CommandHandler('cancel', cancel)],
        allow_reentry=False,
        # Survives a restart or a deploy. `name` is what the persistence layer
        # keys the stored states by, so changing it orphans live conversations.
        name='journal',
        persistent=True,
    )
    application.add_handler(handler)
