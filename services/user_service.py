from __future__ import annotations

from repositories.user_repo import UserRepository


class UserService:
    def __init__(self):
        self._repo = UserRepository()

    def create_or_update(self, telegram_id: int, **kwargs) -> None:
        self._repo.save({'telegram_id': telegram_id, **kwargs})

    def update(self, telegram_id: int, **kwargs) -> None:
        """Set fields on a user who already exists, and do nothing if they don't.

        For writes that are bookkeeping about a user rather than the user
        creating their account — the scheduler's delivery watermarks. A job that
        was already running when someone deleted their account must not upsert
        a skeleton record back into existence.
        """
        self._repo.update(telegram_id, **kwargs)

    def get(self, telegram_id: int) -> dict | None:
        return self._repo.find(telegram_id)

    def get_all_onboarded(self) -> list:
        return self._repo.find_all_onboarded()

    def is_onboarded(self, telegram_id: int) -> bool:
        user = self._repo.find(telegram_id)
        return user is not None and user.get('onboarded', False)
