"""Loads what the export needs and packages the rendered file. See the package docstring."""
from __future__ import annotations

from dataclasses import dataclass

from repositories.user_repo import UserRepository
from services import time_utils
from services.export.digest import build_digest
from services.export.markdown import render_markdown
from services.journal_service import JournalService

# Roughly a month: long enough to cover the gap between fortnightly sessions
# with room to spare, short enough to read in the waiting room. This window is
# free for good; paywalling a user's own recent data is ruled out.
EXPORT_DAYS = 30

# Plus: a quarter, for a review with a therapist or a longer look back.
PLUS_EXPORT_DAYS = 90


@dataclass(frozen=True)
class Export:
    filename: str
    content: bytes
    entry_count: int
    flagged_count: int


class ExportService:
    def __init__(self):
        self._journal = JournalService()
        self._users = UserRepository()

    def build(self, telegram_id: int, days: int = EXPORT_DAYS) -> Export | None:
        """The export for the last `days` local days, or None if there is nothing in it."""
        user = self._users.find(telegram_id) or {}
        timezone_name = user.get('timezone')
        entries = self._journal.get_entries_for_days(telegram_id, days, timezone_name)
        if not entries:
            return None

        tz = time_utils.resolve_timezone(timezone_name, telegram_id)
        today = time_utils.now().astimezone(tz).date()
        digest = build_digest(user.get('name'), entries, tz, today, days)
        return Export(
            filename=f'journal-{today.isoformat()}.md',
            content=render_markdown(digest).encode('utf-8'),
            entry_count=len(digest.entries),
            flagged_count=len(digest.flagged),
        )
