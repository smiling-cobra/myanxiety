from __future__ import annotations

import asyncio
import logging
from datetime import date, datetime
from zoneinfo import ZoneInfo

from messages.markdown import escape_md
from messages.strings import REMINDER_MESSAGE, WEEKLY_SUMMARY_NOTIFICATION
from services import analytics_service as analytics
from services.analytics_service import AnalyticsService
from services.journal_service import JournalService, MIN_ENTRIES_FOR_WEEKLY_SUMMARY
from services.llm_service import LlmService
from services.usage_service import UsageService
from services.user_service import UserService

logger = logging.getLogger(__name__)

_TICK_SECONDS = 60

# How long after a user's reminder time the bot will still deliver. An exact
# minute match needs a tick to land inside a single 60-second slot: a deploy, a
# machine reboot, or a tick that overran drops that day's reminder entirely and
# nobody finds out. The window trades punctuality for delivery — a nudge half an
# hour late is still a useful nudge, a missing one is a broken product.
#
# Two consequences worth knowing. A reminder scheduled inside the hour that DST
# skips forward is missed for that one day, because local time never enters the
# window. And the window never crosses local midnight (see `_minutes_since_due`),
# so a late-evening reminder time is clipped at 00:00 rather than spilling onto
# the next day, where it would be recorded against the wrong date.
_DUE_WINDOW_MINUTES = 30

_WEEKLY_SUMMARY_INTERVAL_DAYS = 7

_REMINDER = 'reminder'
_WEEKLY_SUMMARY = 'weekly-summary'


class SchedulerService:
    """Periodic reminder and weekly-summary delivery.

    The repeating tick only decides *who* is due. Everything it finds is handed
    to a one-shot job per user, so the global loop never waits on a Telegram
    send or — far worse — on an Anthropic call summarising someone's week. Left
    inline, one slow LLM response would delay every other user's reminder behind
    it, and a tick running past its own interval is skipped by APScheduler, so
    the delay compounds into dropped sends.

    The tick is a coroutine on the bot's event loop and so are the jobs. The
    services they call are synchronous, so every one of them is dispatched to a
    worker thread — a blocking Mongo scan or Anthropic call here would stall
    message handling for every user, not just the one being notified.

    Duplicate suppression has two layers, because the due window means a user
    stays due for ~30 ticks rather than one:

    * `_inflight` covers the gap between scheduling a job and that job writing
      its watermark. One process owns the bot (`fly scale count 1`, see
      fly.toml), so an in-memory set is enough.
    * The per-user date watermarks — `last_reminder_sent`,
      `last_weekly_summary_sent`, `last_weekly_summary_check` — survive restarts
      and close the window for the rest of the local day.

    A job that raises writes no watermark, so the next tick retries it; the due
    window is what bounds those retries.
    """

    def __init__(self):
        self._user_svc = UserService()
        self._journal_svc = JournalService()
        self._llm_svc = LlmService()
        self._analytics_svc = AnalyticsService()
        self._usage_svc = UsageService()
        self._inflight: set[tuple[str, int]] = set()

    def start(self, job_queue) -> None:
        # JobQueue is an optional extra in python-telegram-bot v20+. Installed
        # without it, Application.job_queue is None and the bot would boot
        # normally while silently never sending a reminder again.
        if job_queue is None:
            raise RuntimeError(
                'Application.job_queue is None — python-telegram-bot is installed without '
                'the [job-queue] extra, so reminders and weekly summaries cannot run.'
            )
        job_queue.run_repeating(self._tick, interval=_TICK_SECONDS, first=0)
        logger.info('Reminder scheduler started.')

    # ------------------------------------------------------------------
    # The tick: decide who is due, defer the work
    # ------------------------------------------------------------------

    async def _tick(self, context) -> None:
        users = await asyncio.to_thread(self._user_svc.get_all_onboarded)
        for user in users:
            now_local = self._local_now(user)
            if now_local is None or not self._in_due_window(now_local, user):
                continue

            today = now_local.date().isoformat()
            if self._reminder_due(user, today):
                self._defer(context, _REMINDER, user, today)
            if self._weekly_summary_due(user, today):
                self._defer(context, _WEEKLY_SUMMARY, user, today)

    def _defer(self, context, kind: str, user: dict, today: str) -> None:
        key = (kind, user['telegram_id'])
        if key in self._inflight:
            return
        self._inflight.add(key)
        context.job_queue.run_once(
            self._run_job,
            when=0,
            data={'kind': kind, 'user': user, 'today': today},
            name=f'{kind}:{user["telegram_id"]}:{today}',
        )

    async def _run_job(self, context) -> None:
        job = context.job.data
        kind, user, today = job['kind'], job['user'], job['today']
        try:
            if kind == _REMINDER:
                await self._send_reminder(context, user, today)
            else:
                await self._send_weekly_summary(context, user, today)
        except Exception:
            logger.exception('Failed to deliver %s to user %s.', kind, user['telegram_id'])
        finally:
            self._inflight.discard((kind, user['telegram_id']))

    # ------------------------------------------------------------------
    # Delivery
    # ------------------------------------------------------------------

    async def _send_reminder(self, context, user: dict, today: str) -> None:
        # A reminder to do something already done today is a nag, not a nudge.
        # Checked here in the job rather than in the tick, so the tick stays a
        # single scan of `users`. The watermark is still written, which closes
        # the window exactly as a send would.
        already = await asyncio.to_thread(
            self._journal_svc.checked_in_today, user['telegram_id'], user.get('timezone')
        )
        if already:
            await asyncio.to_thread(self._user_svc.update, user['telegram_id'], last_reminder_sent=today)
            await asyncio.to_thread(
                self._analytics_svc.track,
                analytics.REMINDER_SKIPPED,
                user['telegram_id'],
                day=today,
                reason='checked_in',
            )
            return

        await context.bot.send_message(
            chat_id=user['telegram_id'],
            text=REMINDER_MESSAGE.format(name=escape_md(user['name'])),
            parse_mode='Markdown',
        )
        await asyncio.to_thread(
            self._user_svc.update,
            user['telegram_id'],
            last_reminder_sent=today,
        )
        await asyncio.to_thread(
            self._analytics_svc.track, analytics.REMINDER_SENT, user['telegram_id'], day=today
        )
        logger.info('Reminder sent to user %s.', user['telegram_id'])

    async def _send_weekly_summary(self, context, user: dict, today: str) -> None:
        entries = await asyncio.to_thread(
            self._journal_svc.get_weekly_entries, user['telegram_id'], user['timezone']
        )
        if len(entries) < MIN_ENTRIES_FOR_WEEKLY_SUMMARY:
            # Nothing worth summarising this week. Record the decision anyway:
            # `last_weekly_summary_sent` is untouched, so without a separate
            # watermark this scan would repeat on every tick until the window
            # closed, and next week's attempt would still be due on schedule.
            await self._skip_weekly_summary(user, today, 'too_few_entries', entry_count=len(entries))
            return

        # The single most expensive call the bot makes — a whole week of entries
        # in one prompt — and the only one a user never asked for. It is charged
        # to the same daily budget as everything else, so a user who spent their
        # day at the ceiling does not also get billed for this in their sleep.
        allowed = await asyncio.to_thread(
            self._usage_svc.consume_llm, user['telegram_id'], 1, user['timezone']
        )
        if not allowed:
            await asyncio.to_thread(
                self._analytics_svc.track,
                analytics.LLM_BUDGET_EXCEEDED,
                user['telegram_id'],
                surface='weekly_summary_job',
            )
            # The check watermark closes today's window; `last_weekly_summary_sent`
            # is untouched, so tomorrow's tick tries again on a fresh budget.
            await self._skip_weekly_summary(user, today, 'llm_budget', entry_count=len(entries))
            return

        summary = await asyncio.to_thread(self._llm_svc.get_weekly_summary, entries)
        await context.bot.send_message(
            chat_id=user['telegram_id'],
            text=WEEKLY_SUMMARY_NOTIFICATION.format(summary=escape_md(summary)),
            parse_mode='Markdown',
        )
        await asyncio.to_thread(
            self._user_svc.update,
            user['telegram_id'],
            last_weekly_summary_sent=today,
            last_weekly_summary_check=today,
        )
        await asyncio.to_thread(
            self._analytics_svc.track,
            analytics.WEEKLY_SUMMARY_SENT,
            user['telegram_id'],
            entry_count=len(entries),
            day=today,
        )
        logger.info('Weekly summary sent to user %s.', user['telegram_id'])

    async def _skip_weekly_summary(self, user: dict, today: str, reason: str, **props) -> None:
        """Close today's window without sending, and say why in the event stream."""
        await asyncio.to_thread(
            self._user_svc.update,
            user['telegram_id'],
            last_weekly_summary_check=today,
        )
        await asyncio.to_thread(
            self._analytics_svc.track,
            analytics.WEEKLY_SUMMARY_SKIPPED,
            user['telegram_id'],
            reason=reason,
            **props,
        )

    # ------------------------------------------------------------------
    # Due rules
    # ------------------------------------------------------------------

    def _local_now(self, user: dict) -> datetime | None:
        """The user's wall clock, or None if their timezone is unusable.

        Deliberately stricter than `time_utils.resolve_timezone`, which degrades
        to UTC. Presentation can afford that guess; a send cannot — guessing
        here messages someone in the middle of their night.
        """
        try:
            return datetime.now(ZoneInfo(user['timezone']))
        except Exception:
            logger.warning(
                'Unusable timezone %r for user %s — suppressing scheduled sends.',
                user.get('timezone'), user.get('telegram_id'),
            )
            return None

    def _in_due_window(self, now_local: datetime, user: dict) -> bool:
        elapsed = self._minutes_since_due(now_local, user)
        return elapsed is not None and 0 <= elapsed < _DUE_WINDOW_MINUTES

    def _minutes_since_due(self, now_local: datetime, user: dict) -> int | None:
        """Minutes from the user's reminder time to now, within the local day.

        Both sides are minutes-since-local-midnight, so the result goes negative
        the moment the clock rolls over — which is what keeps a 23:50 reminder
        from spilling into the following day and being watermarked against it.
        """
        try:
            hour, minute = (int(part) for part in user['reminder_time'].split(':'))
        except (KeyError, TypeError, ValueError):
            return None
        if not (0 <= hour < 24 and 0 <= minute < 60):
            return None
        return (now_local.hour * 60 + now_local.minute) - (hour * 60 + minute)

    def _reminder_due(self, user: dict, today: str) -> bool:
        return user.get('last_reminder_sent') != today

    def _weekly_summary_due(self, user: dict, today: str) -> bool:
        if user.get('last_weekly_summary_check') == today:
            return False

        last = user.get('last_weekly_summary_sent')
        if not last:
            return True
        try:
            elapsed = date.fromisoformat(today) - date.fromisoformat(last)
        except ValueError:
            logger.warning(
                'Invalid last_weekly_summary_sent value %r for user %s',
                last, user.get('telegram_id'),
            )
            return False
        return elapsed.days >= _WEEKLY_SUMMARY_INTERVAL_DAYS
