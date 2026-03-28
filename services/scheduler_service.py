from __future__ import annotations

import logging
from datetime import datetime
from zoneinfo import ZoneInfo

from messages.strings import REMINDER_MESSAGE
from services.user_service import UserService

logger = logging.getLogger(__name__)

_INTERVAL_SECONDS = 60


class SchedulerService:
    def __init__(self):
        self._user_svc = UserService()

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
                        text=REMINDER_MESSAGE.format(name=user['name']),
                        parse_mode='Markdown',
                    )
                    self._user_svc.create_or_update(
                        user['telegram_id'],
                        last_reminder_sent=self._today(user['timezone']),
                    )
                    logger.info('Reminder sent to user %s.', user['telegram_id'])
                except Exception:
                    logger.exception('Failed to send reminder to user %s.', user['telegram_id'])

    def _is_due(self, user: dict) -> bool:
        try:
            tz = ZoneInfo(user['timezone'])
        except Exception:
            return False
        now = datetime.now(tz)
        h, m = map(int, user['reminder_time'].split(':'))
        return now.hour == h and now.minute == m

    def _sent_today(self, user: dict) -> bool:
        last = user.get('last_reminder_sent')
        if not last:
            return False
        return last == self._today(user['timezone'])

    def _today(self, timezone: str) -> str:
        return datetime.now(ZoneInfo(timezone)).date().isoformat()
