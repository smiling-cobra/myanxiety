from __future__ import annotations

import logging
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from messages.strings import REMINDER_MESSAGE, WEEKLY_SUMMARY_NOTIFICATION
from services.journal_service import JournalService
from services.llm_service import LlmService
from services.user_service import UserService

logger = logging.getLogger(__name__)

_INTERVAL_SECONDS = 60
_MIN_ENTRIES_FOR_WEEKLY_SUMMARY = 3


def _escape_md(text: str) -> str:
    for char in ('*', '_', '`', '['):
        text = text.replace(char, f'\\{char}')
    return text


class SchedulerService:
    def __init__(self):
        self._user_svc = UserService()
        self._journal_svc = JournalService()
        self._llm_svc = LlmService()

    def start(self, job_queue) -> None:
        job_queue.run_repeating(self._send_reminders, interval=_INTERVAL_SECONDS, first=0)
        logger.info('Reminder scheduler started.')

    def _send_reminders(self, context) -> None:
        users = self._user_svc.get_all_onboarded()
        for user in users:
            if self._is_due(user) and not self._sent_today(user):
                try:
                    context.bot.send_message(
                        chat_id=user['telegram_id'],
                        text=REMINDER_MESSAGE.format(name=_escape_md(user['name'])),
                        parse_mode='Markdown',
                    )
                    self._user_svc.create_or_update(
                        user['telegram_id'],
                        last_reminder_sent=self._today(user['timezone']),
                    )
                    logger.info('Reminder sent to user %s.', user['telegram_id'])
                except Exception:
                    logger.exception('Failed to send reminder to user %s.', user['telegram_id'])

            if self._is_weekly_summary_due(user):
                try:
                    self._send_weekly_summary(context, user)
                except Exception:
                    logger.exception('Failed to send weekly summary to user %s.', user['telegram_id'])

    def _send_weekly_summary(self, context, user: dict) -> None:
        entries = self._journal_svc.get_weekly_entries(user['telegram_id'])
        if len(entries) < _MIN_ENTRIES_FOR_WEEKLY_SUMMARY:
            return
        summary = self._llm_svc.get_weekly_summary(entries)
        context.bot.send_message(
            chat_id=user['telegram_id'],
            text=WEEKLY_SUMMARY_NOTIFICATION.format(summary=_escape_md(summary)),
            parse_mode='Markdown',
        )
        self._user_svc.create_or_update(
            user['telegram_id'],
            last_weekly_summary_sent=self._today(user['timezone']),
        )
        logger.info('Weekly summary sent to user %s.', user['telegram_id'])

    def _is_due(self, user: dict) -> bool:
        try:
            tz = ZoneInfo(user['timezone'])
            now = datetime.now(tz)
            h, m = map(int, user['reminder_time'].split(':'))
            return now.hour == h and now.minute == m
        except Exception:
            return False

    def _is_weekly_summary_due(self, user: dict) -> bool:
        if not self._is_due(user):
            return False
        try:
            tz = ZoneInfo(user['timezone'])
            today = datetime.now(tz).date()
        except Exception:
            return False
        last = user.get('last_weekly_summary_sent')
        if not last:
            return True
        from datetime import date as date_cls
        return (today - date_cls.fromisoformat(last)).days >= 7

    def _sent_today(self, user: dict) -> bool:
        last = user.get('last_reminder_sent')
        if not last:
            return False
        return last == self._today(user['timezone'])

    def _today(self, timezone: str) -> str:
        return datetime.now(ZoneInfo(timezone)).date().isoformat()
