"""python-telegram-bot's persisted state, as seen by the `/delete` fan-out.

`bot/persistence.py` owns the reads and writes; this exists so the services
layer can remove one user's rows without importing from `bot/`. The row shapes
are the persistence layer's:

* `ptb_conversations` keys each row by a list of ids — `[chat_id, user_id]` for
  the journal conversation. In a private chat both are the user's id, and
  Mongo matches a scalar against any element of an array field, so one query
  catches the row whichever position the id sits in.
* `ptb_user_data` uses the user's id as `_id`.
"""
from db.db import conversations_collection, user_data_collection


class ConversationRepository:
    def delete_conversations_for_user(self, telegram_id: int) -> int:
        return conversations_collection().delete_many({'key': telegram_id}).deleted_count

    def delete_user_data_for_user(self, telegram_id: int) -> int:
        return user_data_collection().delete_many({'_id': telegram_id}).deleted_count
