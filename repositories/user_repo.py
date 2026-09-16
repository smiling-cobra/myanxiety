from __future__ import annotations

from db.db import users_collection


class UserRepository:
    def save(self, user_data: dict) -> None:
        users_collection().update_one(
            {'telegram_id': user_data['telegram_id']},
            {'$set': user_data},
            upsert=True
        )

    def find(self, telegram_id: int) -> dict | None:
        return users_collection().find_one({'telegram_id': telegram_id}, {'_id': 0})

    def find_all_onboarded(self) -> list:
        return list(users_collection().find({'onboarded': True}, {'_id': 0}))

    def update(self, telegram_id: int, **kwargs) -> None:
        """Set fields on an existing user. Never creates one — see `UserService.update`."""
        users_collection().update_one(
            {'telegram_id': telegram_id},
            {'$set': kwargs}
        )

    def delete_for_user(self, telegram_id: int) -> int:
        return users_collection().delete_many({'telegram_id': telegram_id}).deleted_count
