"""Behavioural instrumentation.

The point of this layer is to answer questions the code cannot: how many people
finish onboarding, how many reminders turn into check-ins, how often the
guidance offer is accepted, what a user costs in Anthropic calls. None of that
is reconstructable later, which is why the event set below is deliberately
broader than what is being asked of it today. Expect to delete some of it.

**Two rules hold this layer in place.**

*Events never carry entry text.* The journal entry is the most sensitive thing
the bot stores; it already lives in the entries collection and goes to Anthropic,
both of which the privacy notice discloses. Copying it into a third store would
create a PII surface nobody disclosed and `/delete` would have to chase.

What actually upholds that rule is the call sites: every prop is a scalar or a
closed-vocabulary label — scores, counts, lengths, category names from
`services/safety.py`, an exception's class name. `_scrub` is a backstop beneath
them, not the guarantee itself. It drops strings long enough to be prose,
wherever they sit — a bare prop, or nested in a list or dict — which catches the
realistic mistake of passing `text=` instead of `text_length=`. It cannot catch
a three-word entry, because nothing about the length of one distinguishes it
from a label. Adding a prop means checking it by eye; the net is there for the
day someone doesn't.

*Tracking never raises.* A failed insert must not cost a user their check-in.
Every path here is wrapped and logged. This is the opposite of the crisis
lexicon's fail-closed rule, and for the opposite reason: a missing analytics row
harms nobody, while a lost check-in harms the person who wrote it.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from repositories.event_repo import EventRepository

logger = logging.getLogger(__name__)

# --- Event taxonomy --------------------------------------------------------
# Onboarding and cohort
ONBOARDING_STARTED = 'onboarding_started'
ONBOARDING_COMPLETED = 'onboarding_completed'
COHORT_RECORDED = 'cohort_recorded'

# The core loop
CHECK_IN_STARTED = 'check_in_started'
CHECK_IN_COMPLETED = 'check_in_completed'
CHECK_IN_FAILED = 'check_in_failed'

# Safety
CRISIS_RESOURCES_SHOWN = 'crisis_resources_shown'
GUIDANCE_OFFERED = 'guidance_offered'
GUIDANCE_ACCEPTED = 'guidance_accepted'
GUIDANCE_DECLINED = 'guidance_declined'

# Scheduled delivery
REMINDER_SENT = 'reminder_sent'
WEEKLY_SUMMARY_SENT = 'weekly_summary_sent'
WEEKLY_SUMMARY_SKIPPED = 'weekly_summary_skipped'

# Read surfaces
HISTORY_VIEWED = 'history_viewed'
STATS_VIEWED = 'stats_viewed'
WEEKLY_SUMMARY_VIEWED = 'weekly_summary_viewed'

# User control
EXPORT_REQUESTED = 'export_requested'
SESSION_FLAG_TOGGLED = 'session_flag_toggled'
DELETE_CANCELLED = 'delete_cancelled'
# Recorded *after* the fan-out, with no telegram_id: every event the user ever
# generated has just been deleted, and this one must not be the row that
# re-links them. Its props are counts, which join to nothing.
ACCOUNT_DELETED = 'account_deleted'

# Spend and failure
LLM_BUDGET_EXCEEDED = 'llm_budget_exceeded'
HANDLER_ERROR = 'handler_error'

# A string prop longer than this is prose, not a label, and prose here is a
# leak. The cap is well above every legitimate value the call sites pass
# (category names, menu labels, ISO dates) and well below a journal entry.
_MAX_PROP_CHARS = 64

# Distinguishes "this value was removed" from a legitimately stored None.
_DROPPED = object()


class AnalyticsService:
    def __init__(self):
        self._repo = EventRepository()

    def track(self, event: str, telegram_id: int | None = None, **props) -> None:
        """Record one event. Never raises, never blocks the caller's flow."""
        try:
            self._repo.save({
                'event': event,
                'telegram_id': telegram_id,
                'created_at': datetime.now(timezone.utc),
                'props': _scrub(event, props),
            })
        except Exception:
            logger.exception('Failed to record analytics event %r', event)

    def recent_for_user(self, telegram_id: int, limit: int = 50) -> list:
        return self._repo.find_recent(telegram_id, limit)


def _scrub(event: str, props: dict) -> dict:
    """Drop props that look like free text, including inside lists and dicts.

    A backstop, not a proof. It catches the realistic mistake — a call site that
    passes `text=` where it meant `text_length=` — and it cannot catch a short
    entry, because a terse one is indistinguishable from a label by length
    alone. The guarantee that events carry no entry text is upheld by the call
    sites passing scalars and closed-vocabulary labels; this is the net under
    them, and `triggers`/`categories` are why it has to look inside containers.
    """
    clean = {}
    for key, value in props.items():
        scrubbed = _scrub_value(value)
        if scrubbed is _DROPPED:
            logger.warning(
                'Dropped analytics prop %r on event %r: longer than %d chars is prose, not a label.',
                key, event, _MAX_PROP_CHARS,
            )
            continue
        clean[key] = scrubbed
    return clean


def _scrub_value(value):
    """The value with over-long strings removed, or `_DROPPED` if nothing remains."""
    if isinstance(value, str):
        return _DROPPED if len(value) > _MAX_PROP_CHARS else value
    if isinstance(value, (list, tuple)):
        kept = [item for item in (_scrub_value(v) for v in value) if item is not _DROPPED]
        # An emptied container is dropped rather than stored: a `categories: []`
        # that used to hold prose reads as "nothing matched", which is a lie.
        return kept if kept or not value else _DROPPED
    if isinstance(value, dict):
        kept = {k: scrubbed for k, v in value.items() if (scrubbed := _scrub_value(v)) is not _DROPPED}
        return kept if kept or not value else _DROPPED
    return value
