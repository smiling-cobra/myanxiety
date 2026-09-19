from db.db import notifications_collection


class NotificationRepository:
    """The `notifications` collection.

    Nothing in the bot writes here any more — delivery state moved onto the user
    record as watermarks — but the collection exists in deployed databases and
    may hold rows from earlier versions. It stays in the `/delete` fan-out until
    the collection itself is dropped.
    """

    def delete_for_user(self, telegram_id: int) -> int:
        return notifications_collection().delete_many({'telegram_id': telegram_id}).deleted_count
