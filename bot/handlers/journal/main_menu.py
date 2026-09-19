"""The main-menu keyboard for a particular user.

Its own module because every handler that returns to the menu needs it, and `menu.py`
imports those handlers.
"""
import asyncio
import logging

from bot.handlers.journal import deps
from bot.keyboards import get_main_menu_keyboard

logger = logging.getLogger(__name__)


async def main_menu_keyboard(telegram_id: int):
    """The menu, with "Add a note" in place of "Check In" once today's check-in is done.

    A failed read shows "Check In" rather than failing the reply. The label is only a
    hint, and a menu that cannot render is worse than one with the wrong wording.
    """
    try:
        checked_in = await asyncio.to_thread(deps.journal_svc.checked_in_today, telegram_id)
    except Exception:
        logger.warning('Could not read check-in state for user %s; showing Check In.', telegram_id, exc_info=True)
        checked_in = False
    return get_main_menu_keyboard(checked_in=bool(checked_in))
