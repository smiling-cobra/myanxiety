"""Per-user daily ceiling on Anthropic calls.

Nothing in this bot capped LLM work before: one check-in is two calls, guidance
is a third, and a weekly summary sends an entire week of entries as one prompt.
A user who checks in fifty times in an evening — bored, testing, or in genuine
distress — costs fifty times what a normal day costs, and nothing anywhere would
have said so.

The ceiling is deliberately loose. It exists to bound a runaway day, not to
ration normal use: the budget below is several times a heavy user's day, so
reaching it means something unusual is happening. Every call site degrades
rather than refuses — the entry is still saved, the trend is still drawn — so
the worst a user at their ceiling experiences is a bot that stops writing prose
back, never one that loses what they wrote.

The day is the user's *local* day, so the reset lands at their midnight rather
than somewhere in their afternoon. An unusable timezone falls back to UTC, which
`time_utils.resolve_timezone` already does: unlike a scheduled send, guessing
wrong here shifts a budget window and wakes nobody up.

This service resolves that timezone itself rather than taking it as an argument
from each caller. The day key has to be identical across every surface — if the
check-in path keyed on UTC and the summary path on local time, one user would
hold two counters either side of midnight and get twice the budget. Callers that
already hold the user record can pass `timezone_name` to skip the lookup; the
answer is the same either way.
"""
from __future__ import annotations

import logging

from repositories.usage_repo import UsageRepository
from repositories.user_repo import UserRepository
from services import time_utils

logger = logging.getLogger(__name__)

# Anthropic calls per user per local day. A heavy but ordinary day — three
# check-ins with guidance and a summary view — is around a dozen.
DAILY_LLM_CALL_BUDGET = 40

_LLM_CALLS = 'llm_calls'


class UsageService:
    def __init__(self):
        self._repo = UsageRepository()
        self._users = UserRepository()

    def consume_llm(self, telegram_id: int, calls: int = 1, timezone_name: str = None) -> bool:
        """Reserve `calls` against today's budget. True if they may proceed.

        Reserves before the work rather than counting after it, so two
        overlapping check-ins cannot both pass the check. A refused reservation
        is handed back, which keeps the stored counter close to a true record of
        calls actually made — it doubles as the per-user spend metric, and
        inflating it with attempts that never reached Anthropic would make that
        useless. (`refund` covers the other direction; see its docstring for the
        one case where the two can still drift.)

        **Never raises.** A metering failure answers "no" rather than
        propagating, for the same reason `AnalyticsService.track` swallows its
        own errors: a handler that called this has a degradation path written and
        tested, and an exception here skips past it to a generic apology. Note
        the two subjects — this fails *closed* for Anthropic, because spend that
        cannot be metered should not be incurred, while every call site stays
        *open* for the user: the entry is still saved, the mood trend still
        renders, and the guidance path still delivers its grounding exercise.
        """
        try:
            day = self._today(telegram_id, timezone_name)
            used = self._repo.increment(telegram_id, day, _LLM_CALLS, calls)
        except Exception:
            logger.exception(
                'Could not meter LLM usage for user %s — refusing the call and degrading.',
                telegram_id,
            )
            return False

        if used <= DAILY_LLM_CALL_BUDGET:
            return True

        self.refund(telegram_id, calls, timezone_name)
        logger.warning(
            'User %s is at the daily LLM ceiling (%d calls) — degrading this request.',
            telegram_id, DAILY_LLM_CALL_BUDGET,
        )
        return False

    def refund(self, telegram_id: int, calls: int = 1, timezone_name: str = None) -> None:
        """Hand back a reservation whose work never reached Anthropic.

        Best-effort and silent on failure: the counter is a spend metric and a
        loose ceiling, and a refund that fails costs its owner a fraction of one
        day's budget. Raising here would undo the whole point of the call sites
        that use it — they are already on an error path when they call it.
        """
        try:
            day = self._today(telegram_id, timezone_name)
            self._repo.increment(telegram_id, day, _LLM_CALLS, -calls)
        except Exception:
            logger.exception('Could not refund %d LLM call(s) for user %s.', calls, telegram_id)

    def used_today(self, telegram_id: int, timezone_name: str = None) -> int:
        doc = self._repo.get(telegram_id, self._today(telegram_id, timezone_name))
        return (doc or {}).get(_LLM_CALLS, 0)

    def _today(self, telegram_id: int, timezone_name: str = None) -> str:
        if timezone_name is None:
            timezone_name = (self._users.find(telegram_id) or {}).get('timezone')
        tz = time_utils.resolve_timezone(timezone_name, telegram_id)
        return time_utils.now().astimezone(tz).date().isoformat()
