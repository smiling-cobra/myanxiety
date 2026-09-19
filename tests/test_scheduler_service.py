"""Tests for SchedulerService due rules, deferral and duplicate suppression.

All datetime.now calls are patched so tests are deterministic.
DB and bot interactions are mocked — no real connections made.

The tick no longer sends anything itself; it schedules one-shot jobs on the job
queue. `_tick_and_deliver` plays the part of the real JobQueue by running what
the tick queued, so a test can still assert on messages in one step.
"""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from services.scheduler_service import _DUE_WINDOW_MINUTES, SchedulerService


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _user(
    telegram_id: int = 1,
    name: str = 'Alice',
    timezone: str = 'Europe/London',
    reminder_time: str = '09:00',
    last_reminder_sent: str | None = None,
    last_weekly_summary_sent: str | None = None,
    last_weekly_summary_check: str | None = None,
) -> dict:
    u = {
        'telegram_id': telegram_id,
        'name': name,
        'timezone': timezone,
        'reminder_time': reminder_time,
        'onboarded': True,
    }
    if last_reminder_sent is not None:
        u['last_reminder_sent'] = last_reminder_sent
    if last_weekly_summary_sent is not None:
        u['last_weekly_summary_sent'] = last_weekly_summary_sent
    if last_weekly_summary_check is not None:
        u['last_weekly_summary_check'] = last_weekly_summary_check
    return u


def _svc() -> SchedulerService:
    svc = SchedulerService.__new__(SchedulerService)
    svc._user_svc = MagicMock()
    svc._journal_svc = MagicMock()
    # A bare MagicMock is truthy, which would read as "already checked in" and
    # silently skip every reminder under test.
    svc._journal_svc.checked_in_today.return_value = False
    svc._llm_svc = MagicMock()
    svc._analytics_svc = MagicMock()
    # The default answer is "under budget": every test that is not about the
    # ceiling should behave as if one does not exist.
    svc._usage_svc = MagicMock()
    svc._usage_svc.consume_llm.return_value = True
    svc._inflight = set()
    return svc


class _FakeUserService:
    """A user store that actually remembers watermark writes.

    MagicMock cannot show that a watermark closes the due window, because the
    write never reaches the dict the next tick reads back.
    """

    def __init__(self, *users: dict):
        self._users = {u['telegram_id']: u for u in users}

    def get_all_onboarded(self) -> list:
        return [dict(u) for u in self._users.values()]

    def update(self, telegram_id: int, **kwargs) -> None:
        # Mirrors UserService.update: a missing user is not created.
        if telegram_id in self._users:
            self._users[telegram_id].update(kwargs)


class _FakeJobQueue:
    """Records run_once calls instead of running them."""

    def __init__(self):
        self.scheduled: list[dict] = []

    def run_once(self, callback, when, data=None, name=None):
        self.scheduled.append({'callback': callback, 'when': when, 'data': data, 'name': name})


def _context() -> MagicMock:
    ctx = MagicMock()
    ctx.bot.send_message = AsyncMock()
    ctx.job_queue = _FakeJobQueue()
    return ctx


async def _drain(ctx) -> int:
    """Run every job the tick queued, as the real JobQueue would. Returns the count."""
    pending, ctx.job_queue.scheduled = ctx.job_queue.scheduled, []
    for job in pending:
        job_ctx = MagicMock()
        job_ctx.bot = ctx.bot
        job_ctx.job_queue = ctx.job_queue
        job_ctx.job.data = job['data']
        await job['callback'](job_ctx)
    return len(pending)


async def _tick_and_deliver(svc, ctx) -> None:
    await svc._tick(ctx)
    await _drain(ctx)


def _fixed_now(hour: int, minute: int, date_iso: str, timezone: str = 'Europe/London'):
    """Return a mock for datetime.now that returns the given time for any tz."""
    from zoneinfo import ZoneInfo
    year, month, day = map(int, date_iso.split('-'))
    dt = datetime(year, month, day, hour, minute, tzinfo=ZoneInfo(timezone))

    def _now(tz=None):
        return dt

    return _now


@contextmanager
def _at(hour: int, minute: int, date_iso: str, timezone: str = 'Europe/London'):
    """Patch the scheduler's clock for the body of a `with` block."""
    with patch('services.scheduler_service.datetime') as mock_dt:
        mock_dt.now.side_effect = _fixed_now(hour, minute, date_iso, timezone)
        yield mock_dt


def _local_now(hour: int, minute: int, date_iso: str = '2026-03-28') -> datetime:
    from zoneinfo import ZoneInfo
    year, month, day = map(int, date_iso.split('-'))
    return datetime(year, month, day, hour, minute, tzinfo=ZoneInfo('Europe/London'))


# ---------------------------------------------------------------------------
# The due window
#
# The old rule was an exact minute match, so a single missed tick — a deploy, a
# reboot, a tick that overran — silently dropped that day's reminder.
# ---------------------------------------------------------------------------

class TestDueWindow:
    def test_exact_reminder_minute_is_due(self):
        assert _svc()._in_due_window(_local_now(9, 0), _user(reminder_time='09:00')) is True

    def test_last_minute_of_window_is_due(self):
        late = _DUE_WINDOW_MINUTES - 1
        assert _svc()._in_due_window(_local_now(9, late), _user(reminder_time='09:00')) is True

    def test_first_minute_past_the_window_is_not_due(self):
        now = _local_now(9, 0) + timedelta(minutes=_DUE_WINDOW_MINUTES)
        assert _svc()._in_due_window(now, _user(reminder_time='09:00')) is False

    def test_before_reminder_time_is_not_due(self):
        assert _svc()._in_due_window(_local_now(8, 59), _user(reminder_time='09:00')) is False

    def test_wrong_hour_is_not_due(self):
        assert _svc()._in_due_window(_local_now(11, 0), _user(reminder_time='09:00')) is False

    def test_window_does_not_cross_local_midnight(self):
        # 23:50 + 30 minutes would reach 00:20 the next day. Sending there would
        # stamp the watermark with the wrong date and re-open the window.
        svc = _svc()
        assert svc._in_due_window(_local_now(23, 55), _user(reminder_time='23:50')) is True
        assert svc._in_due_window(_local_now(0, 10, '2026-03-29'), _user(reminder_time='23:50')) is False

    def test_missing_reminder_time_is_not_due(self):
        user = _user()
        del user['reminder_time']
        assert _svc()._in_due_window(_local_now(9, 0), user) is False

    def test_malformed_reminder_time_is_not_due(self):
        assert _svc()._in_due_window(_local_now(9, 0), _user(reminder_time='not-a-time')) is False

    def test_reminder_time_missing_minutes_is_not_due(self):
        assert _svc()._in_due_window(_local_now(9, 0), _user(reminder_time='09')) is False

    def test_out_of_range_reminder_time_is_not_due(self):
        assert _svc()._in_due_window(_local_now(9, 0), _user(reminder_time='25:00')) is False
        assert _svc()._in_due_window(_local_now(9, 0), _user(reminder_time='09:99')) is False


# ---------------------------------------------------------------------------
# Timezone resolution
#
# Stricter than time_utils.resolve_timezone on purpose: presentation may fall
# back to UTC, a send may not — guessing messages someone at 3am.
# ---------------------------------------------------------------------------

class TestLocalNow:
    def test_invalid_timezone_yields_no_clock(self):
        assert _svc()._local_now(_user(timezone='Invalid/Zone')) is None

    def test_missing_timezone_yields_no_clock(self):
        user = _user()
        del user['timezone']
        assert _svc()._local_now(user) is None

    async def test_user_with_invalid_timezone_is_skipped_entirely(self):
        svc = _svc()
        svc._user_svc.get_all_onboarded.return_value = [_user(timezone='Invalid/Zone')]
        ctx = _context()
        with _at(9, 0, '2026-03-28'):
            await _tick_and_deliver(svc, ctx)
        ctx.bot.send_message.assert_not_called()


# ---------------------------------------------------------------------------
# Reminder watermark
# ---------------------------------------------------------------------------

class TestReminderDue:
    def test_no_watermark_is_due(self):
        assert _svc()._reminder_due(_user(), '2026-03-28') is True

    def test_sent_today_is_not_due(self):
        assert _svc()._reminder_due(_user(last_reminder_sent='2026-03-28'), '2026-03-28') is False

    def test_sent_yesterday_is_due(self):
        assert _svc()._reminder_due(_user(last_reminder_sent='2026-03-27'), '2026-03-28') is True


# ---------------------------------------------------------------------------
# Weekly summary watermarks
# ---------------------------------------------------------------------------

class TestWeeklySummaryDue:
    def test_due_when_never_sent(self):
        assert _svc()._weekly_summary_due(_user(), '2026-03-29') is True

    def test_due_when_7_days_since_last(self):
        user = _user(last_weekly_summary_sent='2026-03-22')
        assert _svc()._weekly_summary_due(user, '2026-03-29') is True

    def test_not_due_when_sent_today(self):
        user = _user(last_weekly_summary_sent='2026-03-29')
        assert _svc()._weekly_summary_due(user, '2026-03-29') is False

    def test_not_due_when_sent_3_days_ago(self):
        user = _user(last_weekly_summary_sent='2026-03-26')
        assert _svc()._weekly_summary_due(user, '2026-03-29') is False

    def test_not_due_when_already_checked_today(self):
        # The "too few entries" outcome. Cadence alone would say due, so without
        # the check watermark the scan repeats on every tick in the window.
        user = _user(last_weekly_summary_check='2026-03-29')
        assert _svc()._weekly_summary_due(user, '2026-03-29') is False

    def test_stale_check_does_not_block_a_later_day(self):
        user = _user(last_weekly_summary_check='2026-03-28')
        assert _svc()._weekly_summary_due(user, '2026-03-29') is True

    def test_malformed_last_sent_returns_false(self):
        user = _user(last_weekly_summary_sent='not-a-date')
        assert _svc()._weekly_summary_due(user, '2026-03-29') is False


# ---------------------------------------------------------------------------
# The tick defers rather than sends
# ---------------------------------------------------------------------------

class TestTickDefersWork:
    async def test_tick_sends_nothing_itself(self):
        svc = _svc()
        svc._user_svc.get_all_onboarded.return_value = [_user(last_weekly_summary_check='2026-03-28')]
        ctx = _context()
        with _at(9, 0, '2026-03-28'):
            await svc._tick(ctx)
        ctx.bot.send_message.assert_not_called()
        assert len(ctx.job_queue.scheduled) == 1

    async def test_tick_does_no_llm_work(self):
        # The point of the phase: a slow Anthropic call must not sit inside the
        # loop that decides everyone else's reminders.
        svc = _svc()
        svc._user_svc.get_all_onboarded.return_value = [_user()]
        svc._journal_svc.get_weekly_entries.return_value = [{'mood_score': i, 'text': 'e'} for i in range(3)]
        ctx = _context()
        with _at(9, 0, '2026-03-29'):
            await svc._tick(ctx)
        svc._llm_svc.get_weekly_summary.assert_not_called()
        svc._journal_svc.get_weekly_entries.assert_not_called()

    async def test_reminder_and_weekly_summary_are_separate_jobs(self):
        svc = _svc()
        svc._user_svc.get_all_onboarded.return_value = [_user()]
        ctx = _context()
        with _at(9, 0, '2026-03-29'):
            await svc._tick(ctx)
        names = [job['name'] for job in ctx.job_queue.scheduled]
        assert names == ['reminder:1:2026-03-29', 'weekly-summary:1:2026-03-29']

    async def test_nothing_scheduled_outside_the_window(self):
        svc = _svc()
        svc._user_svc.get_all_onboarded.return_value = [_user(reminder_time='21:00')]
        ctx = _context()
        with _at(9, 0, '2026-03-28'):
            await svc._tick(ctx)
        assert ctx.job_queue.scheduled == []

    async def test_no_reminder_job_when_already_sent_today(self):
        svc = _svc()
        svc._user_svc.get_all_onboarded.return_value = [
            _user(last_reminder_sent='2026-03-28', last_weekly_summary_check='2026-03-28')
        ]
        ctx = _context()
        with _at(9, 0, '2026-03-28'):
            await svc._tick(ctx)
        assert ctx.job_queue.scheduled == []


# ---------------------------------------------------------------------------
# Duplicate suppression
#
# The window keeps a user due for ~30 consecutive ticks. Two guards stop that
# from becoming 30 messages: the in-flight set covers the gap before the
# watermark is written, the watermark covers everything after.
# ---------------------------------------------------------------------------

class TestDuplicateSuppression:
    async def test_pending_job_is_not_scheduled_twice(self):
        svc = _svc()
        svc._user_svc.get_all_onboarded.return_value = [_user(last_weekly_summary_check='2026-03-28')]
        ctx = _context()
        with _at(9, 0, '2026-03-28'):
            await svc._tick(ctx)
            await svc._tick(ctx)  # job from the first tick has not run yet
        assert len(ctx.job_queue.scheduled) == 1

    async def test_one_reminder_across_the_whole_window(self):
        svc = _svc()
        svc._user_svc = _FakeUserService(_user())
        svc._journal_svc.get_weekly_entries.return_value = []
        ctx = _context()
        for minute in range(_DUE_WINDOW_MINUTES):
            with _at(9, minute, '2026-03-28'):
                await _tick_and_deliver(svc, ctx)
        reminders = [
            call for call in ctx.bot.send_message.call_args_list
            if 'time for your daily check-in' in call.kwargs['text']
        ]
        assert len(reminders) == 1

    async def test_one_weekly_summary_across_the_whole_window(self):
        svc = _svc()
        svc._user_svc = _FakeUserService(_user())
        svc._journal_svc.get_weekly_entries.return_value = [
            {'mood_score': i + 3, 'text': 'e'} for i in range(3)
        ]
        svc._llm_svc.get_weekly_summary.return_value = 'A thoughtful week.'
        ctx = _context()
        for minute in range(_DUE_WINDOW_MINUTES):
            with _at(9, minute, '2026-03-29'):
                await _tick_and_deliver(svc, ctx)
        assert svc._llm_svc.get_weekly_summary.call_count == 1

    async def test_too_few_entries_does_not_rescan_every_tick(self):
        svc = _svc()
        svc._user_svc = _FakeUserService(_user())
        svc._journal_svc.get_weekly_entries.return_value = [{'mood_score': 5, 'text': 'e'}]
        ctx = _context()
        for minute in range(_DUE_WINDOW_MINUTES):
            with _at(9, minute, '2026-03-29'):
                await _tick_and_deliver(svc, ctx)
        assert svc._journal_svc.get_weekly_entries.call_count == 1
        ctx.bot.send_message.assert_called_once()  # the daily reminder only

    async def test_failed_send_is_retried_on_the_next_tick(self):
        svc = _svc()
        svc._user_svc = _FakeUserService(_user())
        svc._journal_svc.get_weekly_entries.return_value = []
        ctx = _context()
        ctx.bot.send_message.side_effect = [Exception('network error'), None]
        with _at(9, 0, '2026-03-28'):
            await _tick_and_deliver(svc, ctx)
        with _at(9, 1, '2026-03-28'):
            await _tick_and_deliver(svc, ctx)
        assert ctx.bot.send_message.call_count == 2

    async def test_failed_send_writes_no_watermark(self):
        svc = _svc()
        user_svc = _FakeUserService(_user())
        svc._user_svc = user_svc
        svc._journal_svc.get_weekly_entries.return_value = []
        ctx = _context()
        ctx.bot.send_message.side_effect = Exception('network error')
        with _at(9, 0, '2026-03-28'):
            await _tick_and_deliver(svc, ctx)
        assert 'last_reminder_sent' not in user_svc.get_all_onboarded()[0]
        assert svc._inflight == set()


# ---------------------------------------------------------------------------
# Delivery
# ---------------------------------------------------------------------------

class TestSendReminder:
    async def test_sends_message_to_due_user(self):
        svc = _svc()
        svc._user_svc.get_all_onboarded.return_value = [_user(last_weekly_summary_check='2026-03-28')]
        ctx = _context()
        with _at(9, 0, '2026-03-28'):
            await _tick_and_deliver(svc, ctx)
        ctx.bot.send_message.assert_called_once()
        assert ctx.bot.send_message.call_args.kwargs['chat_id'] == 1

    async def test_message_contains_user_name(self):
        svc = _svc()
        ctx = _context()
        await svc._send_reminder(ctx, _user(name='Bob'), '2026-03-28')
        assert 'Bob' in ctx.bot.send_message.call_args.kwargs['text']

    async def test_resets_the_menu_button_to_check_in(self):
        """Yesterday's keyboard still says "Add a note"; the reminder replaces it."""
        from bot.keyboards import CHECK_IN
        svc = _svc()
        ctx = _context()
        await svc._send_reminder(ctx, _user(), '2026-03-28')
        assert ctx.bot.send_message.call_args.kwargs['reply_markup'].keyboard[0][0].text == CHECK_IN

    async def test_message_escapes_markdown_special_chars_in_name(self):
        svc = _svc()
        ctx = _context()
        await svc._send_reminder(ctx, _user(name='_Alice_'), '2026-03-28')
        assert '\\_Alice\\_' in ctx.bot.send_message.call_args.kwargs['text']

    async def test_updates_last_reminder_sent_after_send(self):
        svc = _svc()
        ctx = _context()
        await svc._send_reminder(ctx, _user(), '2026-03-28')
        svc._user_svc.update.assert_called_once_with(1, last_reminder_sent='2026-03-28')

    async def test_sends_to_multiple_due_users(self):
        svc = _svc()
        svc._user_svc.get_all_onboarded.return_value = [
            _user(telegram_id=1, name='Alice', last_weekly_summary_check='2026-03-28'),
            _user(telegram_id=2, name='Bob', last_weekly_summary_check='2026-03-28'),
        ]
        ctx = _context()
        with _at(9, 0, '2026-03-28'):
            await _tick_and_deliver(svc, ctx)
        assert ctx.bot.send_message.call_count == 2

    async def test_one_failing_user_does_not_block_the_others(self):
        svc = _svc()
        svc._user_svc.get_all_onboarded.return_value = [
            _user(telegram_id=1, name='Alice', last_weekly_summary_check='2026-03-28'),
            _user(telegram_id=2, name='Bob', last_weekly_summary_check='2026-03-28'),
        ]
        ctx = _context()
        ctx.bot.send_message.side_effect = [Exception('network error'), None]
        with _at(9, 0, '2026-03-28'):
            await _tick_and_deliver(svc, ctx)
        assert ctx.bot.send_message.call_count == 2


class TestReminderAfterCheckIn:
    """Someone who has already checked in today is not reminded to."""

    async def test_no_reminder_when_already_checked_in(self):
        svc = _svc()
        svc._journal_svc.checked_in_today.return_value = True
        ctx = _context()
        await svc._send_reminder(ctx, _user(), '2026-03-28')
        ctx.bot.send_message.assert_not_called()

    async def test_the_check_uses_the_users_timezone(self):
        svc = _svc()
        ctx = _context()
        await svc._send_reminder(ctx, _user(timezone='Asia/Tokyo'), '2026-03-28')
        svc._journal_svc.checked_in_today.assert_called_once_with(1, 'Asia/Tokyo')

    async def test_a_skip_still_closes_the_window(self):
        svc = _svc()
        svc._journal_svc.checked_in_today.return_value = True
        svc._user_svc = _FakeUserService(_user(last_weekly_summary_check='2026-03-28'))
        ctx = _context()
        with _at(9, 0, '2026-03-28'):
            await _tick_and_deliver(svc, ctx)
        with _at(9, 5, '2026-03-28'):
            await svc._tick(ctx)
        assert ctx.job_queue.scheduled == []
        assert svc._journal_svc.checked_in_today.call_count == 1

    async def test_a_skip_is_recorded_not_as_a_send(self):
        svc = _svc()
        svc._journal_svc.checked_in_today.return_value = True
        ctx = _context()
        await svc._send_reminder(ctx, _user(), '2026-03-28')
        tracked = _tracked(svc)
        assert tracked['reminder_skipped'] == {'day': '2026-03-28', 'reason': 'checked_in'}
        assert 'reminder_sent' not in tracked


class TestSendWeeklySummary:
    async def test_sends_when_enough_entries(self):
        svc = _svc()
        svc._journal_svc.get_weekly_entries.return_value = [
            {'mood_score': 7, 'text': 'good'},
            {'mood_score': 5, 'text': 'ok'},
            {'mood_score': 3, 'text': 'rough'},
        ]
        svc._llm_svc.get_weekly_summary.return_value = 'A thoughtful week.'
        ctx = _context()
        await svc._send_weekly_summary(ctx, _user(), '2026-03-29')
        ctx.bot.send_message.assert_called_once()

    async def test_skips_when_too_few_entries(self):
        svc = _svc()
        svc._journal_svc.get_weekly_entries.return_value = [
            {'mood_score': 5, 'text': 'entry'},
            {'mood_score': 4, 'text': 'another'},
        ]
        ctx = _context()
        await svc._send_weekly_summary(ctx, _user(), '2026-03-29')
        ctx.bot.send_message.assert_not_called()
        svc._llm_svc.get_weekly_summary.assert_not_called()

    async def test_too_few_entries_records_the_check(self):
        svc = _svc()
        svc._journal_svc.get_weekly_entries.return_value = []
        await svc._send_weekly_summary(_context(), _user(), '2026-03-29')
        svc._user_svc.update.assert_called_once_with(1, last_weekly_summary_check='2026-03-29')

    async def test_updates_both_watermarks_after_send(self):
        svc = _svc()
        svc._journal_svc.get_weekly_entries.return_value = [
            {'mood_score': i, 'text': 'e'} for i in range(3)
        ]
        svc._llm_svc.get_weekly_summary.return_value = 'Summary.'
        await svc._send_weekly_summary(_context(), _user(), '2026-03-29')
        svc._user_svc.update.assert_called_once_with(
            1, last_weekly_summary_sent='2026-03-29', last_weekly_summary_check='2026-03-29'
        )

    async def test_weekly_summary_sent_alongside_the_reminder(self):
        svc = _svc()
        svc._user_svc.get_all_onboarded.return_value = [_user()]
        svc._journal_svc.get_weekly_entries.return_value = [
            {'mood_score': i + 3, 'text': 'e'} for i in range(3)
        ]
        svc._llm_svc.get_weekly_summary.return_value = 'Summary.'
        ctx = _context()
        with _at(9, 0, '2026-03-29'):
            await _tick_and_deliver(svc, ctx)
        # daily reminder + weekly summary = 2 messages
        assert ctx.bot.send_message.call_count == 2

    async def test_uses_the_users_timezone_for_the_week_window(self):
        svc = _svc()
        svc._journal_svc.get_weekly_entries.return_value = []
        await svc._send_weekly_summary(_context(), _user(timezone='Asia/Tokyo'), '2026-03-29')
        svc._journal_svc.get_weekly_entries.assert_called_once_with(1, 'Asia/Tokyo')


# ---------------------------------------------------------------------------
# start
# ---------------------------------------------------------------------------

class TestStart:
    def test_registers_repeating_tick(self):
        svc = _svc()
        job_queue = MagicMock()
        svc.start(job_queue)
        job_queue.run_repeating.assert_called_once()
        args, kwargs = job_queue.run_repeating.call_args
        assert args[0] == svc._tick
        assert kwargs.get('interval') == 60 or args[1] == 60


# ---------------------------------------------------------------------------
# JobQueue availability
#
# python-telegram-bot v20+ ships JobQueue as an optional extra. Installed
# without it, Application.job_queue is None, and a scheduler that quietly
# accepted that would boot a bot that never sends another reminder.
# ---------------------------------------------------------------------------

class TestJobQueueRequired:
    def test_missing_job_queue_raises_at_startup(self):
        svc = _svc()
        with pytest.raises(RuntimeError, match='job-queue'):
            svc.start(None)

    def test_tick_is_a_coroutine(self):
        import inspect

        assert inspect.iscoroutinefunction(SchedulerService._tick)
        assert inspect.iscoroutinefunction(SchedulerService._run_job)


# ---------------------------------------------------------------------------
# Phase 4 — instrumentation and the LLM spend ceiling
#
# Scheduled sends are the one path the user never initiates, so they are also
# the one path nobody notices going wrong. The events are how it becomes
# visible, and the ceiling is what stops a weekly summary billing a user who
# already spent their day at the limit.
# ---------------------------------------------------------------------------

def _tracked(svc) -> dict:
    return {c.args[0]: c.kwargs for c in svc._analytics_svc.track.call_args_list}


class TestSchedulerInstrumentation:
    async def test_a_delivered_reminder_is_recorded(self):
        svc = _svc()
        svc._user_svc = _FakeUserService(_user(last_weekly_summary_check='2026-03-28'))
        ctx = _context()
        with _at(9, 0, '2026-03-28'):
            await _tick_and_deliver(svc, ctx)
        assert _tracked(svc)['reminder_sent']['day'] == '2026-03-28'

    async def test_a_delivered_weekly_summary_is_recorded_with_its_size(self):
        svc = _svc()
        svc._user_svc = _FakeUserService(_user(last_reminder_sent='2026-03-28'))
        svc._journal_svc.get_weekly_entries.return_value = [{'mood_score': 5, 'text': 'x'}] * 4
        svc._llm_svc.get_weekly_summary.return_value = 'A steady week.'
        ctx = _context()
        with _at(9, 0, '2026-03-28'):
            await _tick_and_deliver(svc, ctx)
        assert _tracked(svc)['weekly_summary_sent']['entry_count'] == 4

    async def test_a_thin_week_is_recorded_as_skipped(self):
        svc = _svc()
        svc._user_svc = _FakeUserService(_user(last_reminder_sent='2026-03-28'))
        svc._journal_svc.get_weekly_entries.return_value = [{'mood_score': 5, 'text': 'x'}]
        ctx = _context()
        with _at(9, 0, '2026-03-28'):
            await _tick_and_deliver(svc, ctx)
        assert _tracked(svc)['weekly_summary_skipped']['reason'] == 'too_few_entries'

    async def test_a_failed_send_records_no_success_event(self):
        svc = _svc()
        svc._user_svc = _FakeUserService(_user(last_weekly_summary_check='2026-03-28'))
        ctx = _context()
        ctx.bot.send_message.side_effect = Exception('Telegram down')
        with _at(9, 0, '2026-03-28'):
            await _tick_and_deliver(svc, ctx)
        assert 'reminder_sent' not in _tracked(svc)


class TestWeeklySummaryAtTheCeiling:
    def _svc_at_ceiling(self) -> SchedulerService:
        svc = _svc()
        svc._usage_svc.consume_llm.return_value = False
        svc._user_svc = _FakeUserService(_user(last_reminder_sent='2026-03-28'))
        svc._journal_svc.get_weekly_entries.return_value = [{'mood_score': 5, 'text': 'x'}] * 4
        return svc

    async def test_no_anthropic_call_is_made(self):
        """The biggest single prompt the bot sends, and one nobody asked for."""
        svc = self._svc_at_ceiling()
        with _at(9, 0, '2026-03-28'):
            await _tick_and_deliver(svc, _context())
        svc._llm_svc.get_weekly_summary.assert_not_called()

    async def test_nothing_is_sent(self):
        svc = self._svc_at_ceiling()
        ctx = _context()
        with _at(9, 0, '2026-03-28'):
            await _tick_and_deliver(svc, ctx)
        ctx.bot.send_message.assert_not_called()

    async def test_the_skip_is_recorded_with_its_reason(self):
        svc = self._svc_at_ceiling()
        with _at(9, 0, '2026-03-28'):
            await _tick_and_deliver(svc, _context())
        assert _tracked(svc)['weekly_summary_skipped']['reason'] == 'llm_budget'
        assert _tracked(svc)['llm_budget_exceeded']['surface'] == 'weekly_summary_job'

    async def test_todays_window_closes_so_the_scan_does_not_repeat(self):
        svc = self._svc_at_ceiling()
        ctx = _context()
        with _at(9, 0, '2026-03-28'):
            await _tick_and_deliver(svc, ctx)
            await _tick_and_deliver(svc, ctx)
        assert svc._journal_svc.get_weekly_entries.call_count == 1

    async def test_the_cadence_watermark_is_untouched_so_tomorrow_retries(self):
        svc = self._svc_at_ceiling()
        with _at(9, 0, '2026-03-28'):
            await _tick_and_deliver(svc, _context())
        stored = svc._user_svc.get_all_onboarded()[0]
        assert stored['last_weekly_summary_check'] == '2026-03-28'
        assert 'last_weekly_summary_sent' not in stored

    async def test_the_budget_is_charged_against_the_users_own_timezone(self):
        """The scheduler holds the timezone already, so it passes it rather than
        letting the service look it up to a different answer."""
        svc = self._svc_at_ceiling()
        with _at(9, 0, '2026-03-28'):
            await _tick_and_deliver(svc, _context())
        assert svc._usage_svc.consume_llm.call_args.args == (1, 1, 'Europe/London')

    async def test_the_reminder_is_unaffected(self):
        """Reminders cost nothing, so the ceiling must not silence them."""
        svc = _svc()
        svc._usage_svc.consume_llm.return_value = False
        svc._user_svc = _FakeUserService(_user(last_weekly_summary_check='2026-03-28'))
        ctx = _context()
        with _at(9, 0, '2026-03-28'):
            await _tick_and_deliver(svc, ctx)
        ctx.bot.send_message.assert_called_once()
