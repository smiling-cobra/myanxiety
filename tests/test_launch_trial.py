"""The one-off launch trial: 30 days of Plus for everyone onboarded before Plus existed."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from repositories.user_repo import UserRepository
from scripts.grant_launch_trial import TRIAL_DAYS, grant_launch_trial
from services.plan_service import SOURCE_LAUNCH_TRIAL, SOURCE_SUBSCRIPTION

NOW = datetime(2026, 9, 24, 10, 0, tzinfo=timezone.utc)


def _save(telegram_id: int, **fields) -> None:
    UserRepository().save({'telegram_id': telegram_id, 'onboarded': True, **fields})


def _until(telegram_id: int):
    value = UserRepository().find(telegram_id).get('plus_until')
    return value.replace(tzinfo=timezone.utc) if value else None


def _run(dry_run: bool = False, now: datetime = NOW) -> int:
    with patch('services.time_utils.now', return_value=now):
        return grant_launch_trial(dry_run=dry_run)


def test_every_onboarded_user_gets_thirty_days():
    _save(1)
    _save(2)
    assert _run() == 2
    assert _until(1) == NOW + timedelta(days=TRIAL_DAYS)
    assert UserRepository().find(1)['plus_source'] == SOURCE_LAUNCH_TRIAL


def test_users_mid_onboarding_are_left_alone():
    UserRepository().save({'telegram_id': 3, 'name': 'New'})
    _run()
    assert _until(3) is None


def test_a_subscriber_is_not_touched():
    _save(4, plus_until=NOW + timedelta(days=3), plus_source=SOURCE_SUBSCRIPTION)
    assert _run() == 0
    assert _until(4) == NOW + timedelta(days=3)
    assert UserRepository().find(4)['plus_source'] == SOURCE_SUBSCRIPTION


def test_a_second_run_changes_nothing():
    _save(1)
    _run()
    assert _run(now=NOW + timedelta(days=5)) == 0
    assert _until(1) == NOW + timedelta(days=TRIAL_DAYS)


def test_a_dry_run_counts_and_writes_nothing():
    _save(1)
    _save(2, plus_until=NOW)
    assert _run(dry_run=True) == 1
    assert _until(1) is None
