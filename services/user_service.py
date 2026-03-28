from __future__ import annotations

from repositories.user_repo import UserRepository


class UserService:
    def __init__(self):
        self._repo = UserRepository()

    def create_or_update(self, telegram_id: int, **kwargs) -> None:
        self._repo.save({'telegram_id': telegram_id, **kwargs})

    def get(self, telegram_id: int) -> dict | None:
        return self._repo.find(telegram_id)

    def get_all_onboarded(self) -> list:
        return self._repo.find_all_onboarded()

    def is_onboarded(self, telegram_id: int) -> bool:
        user = self._repo.find(telegram_id)
        return user is not None and user.get('onboarded', False)
