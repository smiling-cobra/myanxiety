"""Tests for SchedulerService reminder logic.

All datetime.now calls are patched so tests are deterministic.
DB and bot interactions are mocked — no real connections made.
"""
from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock, patch


from services.scheduler_service import SchedulerService


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _user(
    telegram_id: int = 1,
    name: str = 'Alice',
    timezone: str = 'Europe/London',
    reminder_time: str = '09:00',
    last_reminder_sent: str | None = None,
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
    return u


def _svc() -> SchedulerService:
    svc = SchedulerService.__new__(SchedulerService)
    svc._user_svc = MagicMock()
    return svc


def _fixed_now(hour: int, minute: int, date_iso: str, timezone: str = 'Europe/London'):
    """Return a mock for datetime.now that returns the given time for any tz."""
    from zoneinfo import ZoneInfo
    year, month, day = map(int, date_iso.split('-'))
    dt = datetime(year, month, day, hour, minute, tzinfo=ZoneInfo(timezone))

    def _now(tz=None):
        return dt

    return _now


# ---------------------------------------------------------------------------
# _is_due
# ---------------------------------------------------------------------------

class TestIsDue:
    def test_matching_hour_and_minute_is_due(self):
        svc = _svc()
        with patch('services.scheduler_service.datetime') as mock_dt:
            mock_dt.now.side_effect = _fixed_now(9, 0, '2026-03-28')
            assert svc._is_due(_user(reminder_time='09:00')) is True

    def test_wrong_minute_is_not_due(self):
        svc = _svc()
        with patch('services.scheduler_service.datetime') as mock_dt:
            mock_dt.now.side_effect = _fixed_now(9, 1, '2026-03-28')
            assert svc._is_due(_user(reminder_time='09:00')) is False

    def test_wrong_hour_is_not_due(self):
        svc = _svc()
        with patch('services.scheduler_service.datetime') as mock_dt:
            mock_dt.now.side_effect = _fixed_now(10, 0, '2026-03-28')
            assert svc._is_due(_user(reminder_time='09:00')) is False

    def test_invalid_timezone_is_not_due(self):
        svc = _svc()
        assert svc._is_due(_user(timezone='Invalid/Zone')) is False

    def test_missing_reminder_time_is_not_due(self):
        svc = _svc()
        user = _user()
        del user['reminder_time']
        assert svc._is_due(user) is False

    def test_malformed_reminder_time_is_not_due(self):
        svc = _svc()
        assert svc._is_due(_user(reminder_time='not-a-time')) is False

    def test_reminder_time_missing_minutes_is_not_due(self):
        svc = _svc()
        assert svc._is_due(_user(reminder_time='09')) is False


# ---------------------------------------------------------------------------
# _sent_today
# ---------------------------------------------------------------------------

class TestSentToday:
    def test_no_last_sent_is_false(self):
        svc = _svc()
        with patch('services.scheduler_service.datetime') as mock_dt:
            mock_dt.now.side_effect = _fixed_now(9, 0, '2026-03-28')
            assert svc._sent_today(_user()) is False

    def test_sent_today_is_true(self):
        svc = _svc()
        with patch('services.scheduler_service.datetime') as mock_dt:
            mock_dt.now.side_effect = _fixed_now(9, 0, '2026-03-28')
            assert svc._sent_today(_user(last_reminder_sent='2026-03-28')) is True

    def test_sent_yesterday_is_false(self):
        svc = _svc()
        with patch('services.scheduler_service.datetime') as mock_dt:
            mock_dt.now.side_effect = _fixed_now(9, 0, '2026-03-28')
            assert svc._sent_today(_user(last_reminder_sent='2026-03-27')) is False


# ---------------------------------------------------------------------------
# _send_reminders
# ---------------------------------------------------------------------------

class TestSendReminders:
    def _context(self) -> MagicMock:
        ctx = MagicMock()
        ctx.bot.send_message = MagicMock()
        return ctx

    def test_sends_message_to_due_user(self):
        svc = _svc()
        svc._user_svc.get_all_onboarded.return_value = [_user()]
        ctx = self._context()
        with patch('services.scheduler_service.datetime') as mock_dt:
            mock_dt.now.side_effect = _fixed_now(9, 0, '2026-03-28')
            svc._send_reminders(ctx)
        ctx.bot.send_message.assert_called_once()
        assert ctx.bot.send_message.call_args.kwargs['chat_id'] == 1

    def test_message_contains_user_name(self):
        svc = _svc()
        svc._user_svc.get_all_onboarded.return_value = [_user(name='Bob')]
        ctx = self._context()
        with patch('services.scheduler_service.datetime') as mock_dt:
            mock_dt.now.side_effect = _fixed_now(9, 0, '2026-03-28')
            svc._send_reminders(ctx)
        sent_text = ctx.bot.send_message.call_args.kwargs['text']
        assert 'Bob' in sent_text

    def test_does_not_send_when_not_due(self):
        svc = _svc()
        svc._user_svc.get_all_onboarded.return_value = [_user(reminder_time='21:00')]
        ctx = self._context()
        with patch('services.scheduler_service.datetime') as mock_dt:
            mock_dt.now.side_effect = _fixed_now(9, 0, '2026-03-28')
            svc._send_reminders(ctx)
        ctx.bot.send_message.assert_not_called()

    def test_does_not_send_when_already_sent_today(self):
        svc = _svc()
        svc._user_svc.get_all_onboarded.return_value = [
            _user(reminder_time='09:00', last_reminder_sent='2026-03-28')
        ]
        ctx = self._context()
        with patch('services.scheduler_service.datetime') as mock_dt:
            mock_dt.now.side_effect = _fixed_now(9, 0, '2026-03-28')
            svc._send_reminders(ctx)
        ctx.bot.send_message.assert_not_called()

    def test_updates_last_reminder_sent_after_send(self):
        svc = _svc()
        svc._user_svc.get_all_onboarded.return_value = [_user()]
        ctx = self._context()
        with patch('services.scheduler_service.datetime') as mock_dt:
            mock_dt.now.side_effect = _fixed_now(9, 0, '2026-03-28')
            svc._send_reminders(ctx)
        svc._user_svc.create_or_update.assert_called_once_with(
            1, last_reminder_sent='2026-03-28'
        )

    def test_skips_failed_user_and_continues(self):
        svc = _svc()
        user_ok = _user(telegram_id=2, name='Bob')
        user_bad = _user(telegram_id=1, name='Alice')
        svc._user_svc.get_all_onboarded.return_value = [user_bad, user_ok]
        ctx = self._context()
        ctx.bot.send_message.side_effect = [Exception('network error'), None]
        with patch('services.scheduler_service.datetime') as mock_dt:
            mock_dt.now.side_effect = _fixed_now(9, 0, '2026-03-28')
            svc._send_reminders(ctx)
        # Bob's message still attempted despite Alice failing
        assert ctx.bot.send_message.call_count == 2

    def test_message_escapes_markdown_special_chars_in_name(self):
        svc = _svc()
        svc._user_svc.get_all_onboarded.return_value = [_user(name='_Alice_')]
        ctx = self._context()
        with patch('services.scheduler_service.datetime') as mock_dt:
            mock_dt.now.side_effect = _fixed_now(9, 0, '2026-03-28')
            svc._send_reminders(ctx)
        sent_text = ctx.bot.send_message.call_args.kwargs['text']
        assert '\\_Alice\\_' in sent_text

    def test_sends_to_multiple_due_users(self):
        svc = _svc()
        svc._user_svc.get_all_onboarded.return_value = [
            _user(telegram_id=1, name='Alice'),
            _user(telegram_id=2, name='Bob'),
        ]
        ctx = self._context()
        with patch('services.scheduler_service.datetime') as mock_dt:
            mock_dt.now.side_effect = _fixed_now(9, 0, '2026-03-28')
            svc._send_reminders(ctx)
        assert ctx.bot.send_message.call_count == 2


# ---------------------------------------------------------------------------
# start
# ---------------------------------------------------------------------------

class TestStart:
    def test_registers_repeating_job(self):
        svc = _svc()
        job_queue = MagicMock()
        svc.start(job_queue)
        job_queue.run_repeating.assert_called_once()
        args, kwargs = job_queue.run_repeating.call_args
        assert args[0] == svc._send_reminders
        assert kwargs.get('interval') == 60 or args[1] == 60
