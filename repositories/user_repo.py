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

    def extend_plus(self, telegram_id: int, until, source: str) -> bool:
        """Move `plus_until` to `until` only if that is later. One conditional update, so a
        concurrent writer can never be overwritten with an earlier end. Never creates a user."""
        result = users_collection().update_one(
            {'telegram_id': telegram_id, '$or': [{'plus_until': None}, {'plus_until': {'$lt': until}}]},
            {'$set': {'plus_until': until, 'plus_source': source}},
        )
        return result.modified_count == 1

    def delete_for_user(self, telegram_id: int) -> int:
        return users_collection().delete_many({'telegram_id': telegram_id}).deleted_count
