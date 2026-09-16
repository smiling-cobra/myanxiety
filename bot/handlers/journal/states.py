"""Conversation state identifiers.

**These integers are persisted.** `MongoPersistence` writes the raw value into
`ptb_conversations` and reads it straight back on the next boot, so the number a
state happens to have is part of the on-disk format, not an implementation
detail. A new state may only be *appended*; inserting one in the middle silently
reinterprets every stored row after it — a user resting on the main menu would
come back as mid-onboarding, and a user mid-check-in would have their next
message routed to a handler expecting something else entirely.

That is why `ONBOARDING_THERAPY` sits at the end rather than in flow order: it
was added after the others had already been written to the database.
`tests/test_states.py` pins these values so a future insertion fails CI instead
of production.
"""
(
    ONBOARDING_NAME,
    ONBOARDING_TIMEZONE,
    ONBOARDING_TIME,
    MAIN_MENU,
    CHECK_IN_MOOD,
    CHECK_IN_TEXT,
    CHECK_IN_GUIDANCE_OFFER,
    ONBOARDING_THERAPY,
) = range(8)

LOW_MOOD_THRESHOLD = 4
CRISIS_MOOD_THRESHOLD = 2
