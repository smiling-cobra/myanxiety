"""Loads what the export needs and packages the rendered file. See the package docstring."""
from __future__ import annotations

from dataclasses import dataclass

from repositories.user_repo import UserRepository
from services import time_utils
from services.export.digest import build_digest
from services.export.markdown import render_markdown
from services.journal_service import JournalService

# Roughly a month: long enough to cover the gap between fortnightly sessions
# with room to spare, short enough to read in the waiting room.
EXPORT_DAYS = 30


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

    def build(self, telegram_id: int) -> Export | None:
        """The export for the last `EXPORT_DAYS` local days, or None if there is nothing in it."""
        user = self._users.find(telegram_id) or {}
        timezone_name = user.get('timezone')
        entries = self._journal.get_entries_for_days(telegram_id, EXPORT_DAYS, timezone_name)
        if not entries:
            return None

        tz = time_utils.resolve_timezone(timezone_name, telegram_id)
        today = time_utils.now().astimezone(tz).date()
        digest = build_digest(user.get('name'), entries, tz, today)
        return Export(
            filename=f'journal-{today.isoformat()}.md',
            content=render_markdown(digest).encode('utf-8'),
            entry_count=len(digest.entries),
            flagged_count=len(digest.flagged),
        )
