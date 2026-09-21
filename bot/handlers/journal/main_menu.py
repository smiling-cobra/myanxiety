"""The per-user main menu, and the check-in read that decides its label.

Its own module because every handler that returns to the menu needs it, and `menu.py`
imports those handlers.
"""
import asyncio
import logging

from bot.handlers.journal import deps
from bot.keyboards import get_main_menu_keyboard

logger = logging.getLogger(__name__)


async def checked_in_today(telegram_id: int) -> bool:
    """Whether today's check-in is done, for wording only. A failed read answers False.

    Only labels and prompts are chosen from this. Whether an entry is the daily check-in
    or a note is decided when it is saved, so a wrong answer here costs a word, and
    failing the reply over it would cost the user their tap.
    """
    try:
        return bool(await asyncio.to_thread(deps.journal_svc.checked_in_today, telegram_id))
    except Exception:
        logger.warning('Could not read check-in state for user %s; treating as not checked in.',
                       telegram_id, exc_info=True)
        return False


async def main_menu_keyboard(telegram_id: int):
    """The menu, with "Add a note" in place of "Check In" once today's check-in is done."""
    return get_main_menu_keyboard(checked_in=await checked_in_today(telegram_id))
