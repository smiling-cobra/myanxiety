"""The conversation-state integers are an on-disk format, so they are pinned here.

`MongoPersistence` writes the raw int into `ptb_conversations` and reads it back
on the next boot. Renumbering a state therefore reinterprets every stored row
after it: on the deploy that ships the change, a user resting on the main menu
comes back as mid-onboarding, and a user mid-check-in has their next message
routed to a handler expecting something else. Nothing fails loudly — the bot
just answers the wrong question, once, for everyone.

That is a production-only failure, invisible to every other test in this suite,
because they all start from an empty database. These assertions are the thing
that makes it a CI failure instead. A new state must be *appended*; if adding one
turns these red, that is the test working.
"""
from __future__ import annotations

from bot.handlers.journal import states


class TestPersistedStateValues:
    def test_the_stored_values_are_unchanged(self):
        assert states.ONBOARDING_NAME == 0
        assert states.ONBOARDING_TIMEZONE == 1
        assert states.ONBOARDING_TIME == 2
        assert states.MAIN_MENU == 3
        assert states.CHECK_IN_MOOD == 4
        assert states.CHECK_IN_TEXT == 5
        assert states.CHECK_IN_GUIDANCE_OFFER == 6

    def test_the_therapy_state_was_appended_rather_than_inserted(self):
        """Added in Phase 4, after the six above had already been persisted."""
        assert states.ONBOARDING_THERAPY == 7

    def test_every_state_is_distinct(self):
        values = [
            states.ONBOARDING_NAME,
            states.ONBOARDING_TIMEZONE,
            states.ONBOARDING_TIME,
            states.MAIN_MENU,
            states.CHECK_IN_MOOD,
            states.CHECK_IN_TEXT,
            states.CHECK_IN_GUIDANCE_OFFER,
            states.ONBOARDING_THERAPY,
        ]
        assert len(set(values)) == len(values)


class TestMoodThresholds:
    def test_crisis_is_stricter_than_low(self):
        """Ordering these two wrongly would offer grounding techniques to the
        calmer user and generic coping tips to the one in crisis."""
        assert states.CRISIS_MOOD_THRESHOLD < states.LOW_MOOD_THRESHOLD
