"""Boot-time index creation for the main query paths.

Every read the bot makes is scoped to one user, and none of the collections below
had an index for it, so each lookup was a full collection scan: the scheduler's
user scan every 60 seconds, the streak read on every check-in, the entry reads
behind history, stats and export.

`events` and `usage` are not here. Their repositories create their own indexes on
first write, because theirs carry behaviour (TTL retention, and the unique key that
makes the LLM budget counter atomic) and must exist even if boot never reached this.

`create_index` is idempotent, so running this on every boot costs a round trip per
index once they exist.
"""
from __future__ import annotations

import logging

from pymongo import ASCENDING, DESCENDING
from pymongo.database import Database
from pymongo.errors import PyMongoError

logger = logging.getLogger(__name__)

# (collection, keys, options). Named explicitly so a failure log says which one.
INDEXES = (
    # `find`, `update` and every upsert. Unique, so a racing upsert cannot create
    # a second account for the same person.
    ('users', [('telegram_id', ASCENDING)], {'unique': True, 'name': 'telegram_id_unique'}),
    # The scheduler tick's scan.
    ('users', [('onboarded', ASCENDING)], {'name': 'onboarded'}),
    # History, the latest entry for /flag, the weekly and export windows, counts
    # and deletion. Descending to match the newest-first reads; the ascending
    # window read walks it backwards.
    ('entries', [('telegram_id', ASCENDING), ('created_at', DESCENDING)], {'name': 'telegram_id_created_at'}),
    # Read on every check-in and every menu render. Unique for the same reason as users.
    ('streaks', [('telegram_id', ASCENDING)], {'unique': True, 'name': 'telegram_id_unique'}),
    # Only /delete reads it, but a scan there grows with every user who ever had a row.
    ('notifications', [('telegram_id', ASCENDING)], {'name': 'telegram_id'}),
    # MongoPersistence writes a row on every conversation state change, matched on both.
    ('ptb_conversations', [('name', ASCENDING), ('key', ASCENDING)], {'name': 'name_key'}),
)


def ensure_indexes(db: Database) -> list[str]:
    """Create the indexes, returning the names of any that failed.

    Connectivity is checked first and a failure there raises: a bot that cannot
    reach its database at boot should crash visibly, not start and fail on every
    message. A failure on a single index is logged and skipped instead. The bot is
    correct without an index, only slower, and the likely cause (existing duplicate
    rows under a unique index) needs a person, not a restart loop.
    """
    db.command('ping')

    failed = []
    for collection, keys, options in INDEXES:
        label = f'{collection}.{options["name"]}'
        try:
            db[collection].create_index(keys, **options)
        except PyMongoError:
            logger.error(
                'Could not create index %s. Queries still work, but scan the collection. '
                'For a unique index, check for duplicate rows first.', label, exc_info=True,
            )
            failed.append(label)
    return failed
