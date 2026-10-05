"""Give every existing user 30 days of Plus, once, when Plus launches.

Plus moves the weekly AI summary behind the paywall, and existing users already
have it. A free month means nobody loses anything overnight, and each person
sees what Plus is before deciding.

Run once, right after the deploy that ships Plus, on the production machine:

    fly ssh console -C "python -m scripts.grant_launch_trial --dry-run"
    fly ssh console -C "python -m scripts.grant_launch_trial"

Needs only MONGODB_URI — it sends no messages. Idempotent: only onboarded users
with no `plus_until` at all are touched, so a second run, or a run after someone
has already subscribed or been given Plus, changes nothing for them.
"""
from __future__ import annotations

import argparse
import logging
from datetime import timedelta

from dotenv import load_dotenv

logger = logging.getLogger(__name__)

TRIAL_DAYS = 30

_ELIGIBLE = {'onboarded': True, 'plus_until': {'$exists': False}}


def grant_launch_trial(dry_run: bool = False) -> int:
    """Grant the trial to every eligible user. Returns how many were (or would be) granted."""
    from db.db import users_collection
    from services import time_utils
    from services.plan_service import SOURCE_LAUNCH_TRIAL

    users = users_collection()
    if dry_run:
        return users.count_documents(_ELIGIBLE)

    until = time_utils.now() + timedelta(days=TRIAL_DAYS)
    result = users.update_many(
        _ELIGIBLE, {'$set': {'plus_until': until, 'plus_source': SOURCE_LAUNCH_TRIAL}}
    )
    return result.modified_count


def main() -> None:
    logging.basicConfig(level=logging.INFO, format='%(levelname)s %(message)s')
    load_dotenv()
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--dry-run', action='store_true', help='count eligible users without writing')
    args = parser.parse_args()

    count = grant_launch_trial(dry_run=args.dry_run)
    verb = 'would be granted' if args.dry_run else 'granted'
    logger.info('%d user(s) %s a %d-day Plus trial.', count, verb, TRIAL_DAYS)


if __name__ == '__main__':
    main()
