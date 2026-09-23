"""Which callback the real ConversationHandler picks for a message in a given state.

Every other handler test calls a callback directly, which proves what the
callback does and nothing about whether a user's message ever reaches it. That
gap hid a routing bug for a whole phase: with `allow_reentry=True`, the entry
points are consulted *before* the current state's handlers, and the lost-state
entry point matches any text — so a mood rating, a journal entry or an
onboarding answer was handed to `recover_state` instead of the step waiting for
it. No callback was wrong; the wiring was.

These tests build the handler through `register()` and ask `check_update`
directly. No Application runs and no callback is invoked.
"""
from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock

import pytest
from telegram import Chat, Message, MessageEntity, Update, User

from bot.handlers import journal

USER_ID = 12345


@pytest.fixture
def conversation():
    app = MagicMock()
    journal.register(app)
    return app.add_handler.call_args.args[0]


def _update(text: str) -> Update:
    entities = [MessageEntity(MessageEntity.BOT_COMMAND, 0, len(text.split()[0]))] if text.startswith('/') else None
    message = Message(
        1, datetime.now(), Chat(USER_ID, Chat.PRIVATE),
        from_user=User(USER_ID, 'Sam', False), text=text, entities=entities,
    )
    # CommandHandler reads the bot's username to tell `/start` from `/start@other_bot`.
    message.set_bot(MagicMock(username='journal_bot'))
    return Update(1, message=message)


def _route(conversation, state: int | None, text: str) -> str | None:
    """The name of the callback that would handle `text` while in `state`."""
    key = (USER_ID, USER_ID)
    if state is None:
        conversation._conversations.pop(key, None)
    else:
        conversation._conversations[key] = state
    result = conversation.check_update(_update(text))
    return result[2].callback.__name__ if result else None


class TestTextReachesTheStepWaitingForIt:
    @pytest.mark.parametrize('state, text, expected', [
        (journal.ONBOARDING_NAME, 'Sam', 'handle_name'),
        (journal.ONBOARDING_TIMEZONE, 'Europe/London', 'handle_timezone'),
        (journal.ONBOARDING_TIME, '09:00', 'handle_reminder_time'),
        (journal.ONBOARDING_THERAPY, 'Yes', 'handle_therapy'),
        (journal.MAIN_MENU, '📝 Check In', 'handle_main_menu'),
        (journal.MAIN_MENU, '🗒 Add a note', 'handle_main_menu'),
        (journal.CHECK_IN_MOOD, '5', 'handle_mood'),
        (journal.CHECK_IN_TEXT, 'a long day at work', 'handle_entry_text'),
        (journal.CHECK_IN_GUIDANCE_OFFER, 'No thanks', 'handle_guidance_offer'),
        (journal.DELETE_CONFIRM, '🗑 Yes, delete everything', 'handle_delete_confirmation'),
    ])
    def test_state_handler_wins_over_lost_state_recovery(self, conversation, state, text, expected):
        assert _route(conversation, state, text) == expected

    def test_text_with_no_conversation_is_recovered(self, conversation):
        assert _route(conversation, None, 'hello') == 'recover_state'


class TestCommandsWorkFromAnywhere:
    @pytest.mark.parametrize('command, expected', [
        ('/start', 'start'),
        ('/history', 'show_history'),
        ('/stats', 'show_stats'),
        ('/summary', 'show_weekly_summary'),
        ('/export', 'send_export'),
        ('/delete', 'request_delete'),
        ('/flag', 'toggle_flag'),
    ])
    def test_before_any_conversation(self, conversation, command, expected):
        assert _route(conversation, None, command) == expected

    @pytest.mark.parametrize('command, expected', [
        ('/start', 'start'),
        ('/history', 'show_history'),
        ('/export', 'send_export'),
        ('/delete', 'request_delete'),
        ('/flag', 'toggle_flag'),
        ('/cancel', 'cancel'),
    ])
    @pytest.mark.parametrize('state', [journal.CHECK_IN_MOOD, journal.CHECK_IN_TEXT, journal.ONBOARDING_NAME])
    def test_mid_conversation(self, conversation, state, command, expected):
        assert _route(conversation, state, command) == expected

    def test_a_command_while_confirming_deletion_is_not_a_confirmation(self, conversation):
        assert _route(conversation, journal.DELETE_CONFIRM, '/history') == 'show_history'
