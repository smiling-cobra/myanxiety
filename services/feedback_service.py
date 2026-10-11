"""Storing what users send through /feedback.

The stored row is the record. Forwarding a copy to the admins happens in the
handler, because it needs the Bot, and a failed forward loses nothing.

The daily cap is a guard against a stuck client or a flood, not a judgement on
anyone: `DAILY_FEEDBACK_LIMIT` messages per local day, counted from the rows
themselves, so there is no counter to drift and nothing extra for /delete.
"""
from __future__ import annotations

from datetime import datetime, time

from repositories.feedback_repo import FeedbackRepository
from repositories.user_repo import UserRepository
from services import time_utils
from services.plan_service import PlanService

MAX_FEEDBACK_LENGTH = 2000
DAILY_FEEDBACK_LIMIT = 5


class FeedbackService:
    def __init__(self):
        self._feedback = FeedbackRepository()
        self._users = UserRepository()
        self._plan = PlanService()

    def can_submit(self, telegram_id: int) -> bool:
        """Whether the user is under today's cap."""
        return self._feedback.count_since(telegram_id, self._local_midnight(telegram_id)) < DAILY_FEEDBACK_LIMIT

    def submit(self, telegram_id: int, text: str) -> bool:
        """Store one message. False, with nothing stored, if the user is at today's cap."""
        if not self.can_submit(telegram_id):
            return False
        self._feedback.add({
            'telegram_id': telegram_id,
            'text': text,
            'created_at': time_utils.now(),
            'is_plus': self._plan.is_plus(telegram_id),
        })
        return True

    def _local_midnight(self, telegram_id: int) -> datetime:
        user = self._users.find(telegram_id) or {}
        tz = time_utils.resolve_timezone(user.get('timezone'), telegram_id)
        today = time_utils.now().astimezone(tz).date()
        return datetime.combine(today, time.min, tzinfo=tz).astimezone(time_utils.UTC)
