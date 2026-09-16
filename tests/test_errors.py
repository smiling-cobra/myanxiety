"""Tests for the global error handler.

Without one, an exception escaping a handler leaves the user with no reply at
all — waiting on a bot that has silently dropped their message.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

from telegram import Update

from bot.handlers.errors import handle_error
from messages.strings import ERROR_GENERIC


def _context(error: Exception) -> MagicMock:
    ctx = MagicMock()
    ctx.error = error
    return ctx


def _update() -> MagicMock:
    update = MagicMock(spec=Update)
    update.effective_message = MagicMock()
    update.effective_message.reply_text = AsyncMock()
    return update


class TestErrorHandler:
    async def test_tells_the_user_something_went_wrong(self):
        update = _update()
        await handle_error(update, _context(RuntimeError('boom')))
        assert update.effective_message.reply_text.call_args.args[0] == ERROR_GENERIC

    async def test_reattaches_the_main_menu_keyboard(self):
        """The user is re-anchored: whatever state was lost, their next tap works."""
        update = _update()
        await handle_error(update, _context(RuntimeError('boom')))
        assert update.effective_message.reply_text.call_args.kwargs['reply_markup'] is not None

    async def test_ignores_errors_that_have_no_update(self):
        # A failure inside a scheduled job arrives with no update to answer.
        await handle_error(None, _context(RuntimeError('boom')))

    async def test_ignores_a_non_update_object(self):
        await handle_error(object(), _context(RuntimeError('boom')))

    async def test_survives_a_failure_while_reporting_the_failure(self):
        update = _update()
        update.effective_message.reply_text = AsyncMock(side_effect=Exception('telegram down'))
        await handle_error(update, _context(RuntimeError('boom')))

    async def test_handles_an_update_with_no_message(self):
        update = MagicMock(spec=Update)
        update.effective_message = None
        await handle_error(update, _context(RuntimeError('boom')))


# ---------------------------------------------------------------------------
# Phase 4 — instrumentation
#
# An uncaught exception is invisible in the product: the user simply stops
# replying, which looks exactly like losing interest.
# ---------------------------------------------------------------------------

class TestErrorInstrumentation:
    async def test_the_failure_is_recorded(self):
        with patch('bot.handlers.journal.deps.analytics_svc') as analytics:
            await handle_error(_update(), _context(ValueError('boom')))
        assert analytics.track.call_args.args[0] == 'handler_error'

    async def test_only_the_exception_type_is_recorded(self):
        """An exception message can quote whatever the user typed."""
        secret = 'my private journal entry'
        with patch('bot.handlers.journal.deps.analytics_svc') as analytics:
            await handle_error(_update(), _context(ValueError(secret)))
        assert analytics.track.call_args.kwargs == {'error_type': 'ValueError'}

    async def test_a_failure_with_no_update_behind_it_is_still_recorded(self):
        with patch('bot.handlers.journal.deps.analytics_svc') as analytics:
            await handle_error(object(), _context(RuntimeError('job failed')))
        assert analytics.track.call_args.args[1] is None

    async def test_the_user_is_still_answered(self):
        """Instrumentation must never come at the cost of the reply."""
        update = _update()
        with patch('bot.handlers.journal.deps.analytics_svc'):
            await handle_error(update, _context(ValueError('boom')))
        assert update.effective_message.reply_text.call_args.args[0] == ERROR_GENERIC
