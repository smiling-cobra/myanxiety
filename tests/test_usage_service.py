"""Tests for the per-user daily Anthropic ceiling.

The properties that matter: the budget is a real limit, a refused reservation
does not inflate the counter that doubles as the spend metric, and every surface
shares one day key — a user must not get two budgets by checking in either side
of midnight.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

from repositories.usage_repo import USAGE_RETENTION_DAYS, UsageRepository
from repositories.user_repo import UserRepository
from services.usage_service import DAILY_LLM_CALL_BUDGET, UsageService
from db.db import usage_collection

_USER = 42


@pytest.fixture
def svc() -> UsageService:
    return UsageService()


def _at(when: datetime):
    """Freeze the clock the day key is derived from."""
    return patch('services.time_utils.now', return_value=when)


class TestBudget:
    def test_a_fresh_user_is_under_budget(self, svc):
        assert svc.consume_llm(_USER) is True

    def test_usage_accumulates(self, svc):
        svc.consume_llm(_USER, 2)
        svc.consume_llm(_USER, 3)
        assert svc.used_today(_USER) == 5

    def test_the_last_call_inside_the_budget_is_allowed(self, svc):
        svc.consume_llm(_USER, DAILY_LLM_CALL_BUDGET - 1)
        assert svc.consume_llm(_USER, 1) is True
        assert svc.used_today(_USER) == DAILY_LLM_CALL_BUDGET

    def test_the_first_call_past_the_budget_is_refused(self, svc):
        svc.consume_llm(_USER, DAILY_LLM_CALL_BUDGET)
        assert svc.consume_llm(_USER, 1) is False

    def test_a_multi_call_reservation_that_would_overshoot_is_refused_whole(self, svc):
        """A check-in needs two calls; granting one of them would be worse than none."""
        svc.consume_llm(_USER, DAILY_LLM_CALL_BUDGET - 1)
        assert svc.consume_llm(_USER, 2) is False

    def test_a_refused_reservation_does_not_inflate_the_counter(self, svc):
        """The counter is also the spend metric — attempts that never reached
        Anthropic must not appear in it."""
        svc.consume_llm(_USER, DAILY_LLM_CALL_BUDGET)
        svc.consume_llm(_USER, 5)
        assert svc.used_today(_USER) == DAILY_LLM_CALL_BUDGET

    def test_the_ceiling_is_logged(self, svc, caplog):
        svc.consume_llm(_USER, DAILY_LLM_CALL_BUDGET)
        svc.consume_llm(_USER, 1)
        assert str(_USER) in caplog.text

    def test_budgets_are_per_user(self, svc):
        svc.consume_llm(_USER, DAILY_LLM_CALL_BUDGET)
        assert svc.consume_llm(99) is True


class TestDayBoundary:
    def _user_in(self, timezone_name: str) -> None:
        UserRepository().save({'telegram_id': _USER, 'timezone': timezone_name, 'onboarded': True})

    def test_the_counter_resets_on_the_next_day(self, svc):
        monday = datetime(2026, 3, 23, 12, 0, tzinfo=timezone.utc)
        with _at(monday):
            svc.consume_llm(_USER, DAILY_LLM_CALL_BUDGET)
            assert svc.consume_llm(_USER, 1) is False
        with _at(monday + timedelta(days=1)):
            assert svc.consume_llm(_USER, 1) is True

    def test_the_day_is_the_users_local_day(self, svc):
        """23:00 UTC is already tomorrow in Tokyo, so the budget has reset there."""
        self._user_in('Asia/Tokyo')
        late_utc = datetime(2026, 3, 23, 23, 0, tzinfo=timezone.utc)
        with _at(late_utc - timedelta(hours=4)):   # 23 Mar 19:00 UTC -> 24 Mar 04:00 Tokyo
            svc.consume_llm(_USER, DAILY_LLM_CALL_BUDGET)
        with _at(datetime(2026, 3, 24, 16, 0, tzinfo=timezone.utc)):  # 25 Mar in Tokyo
            assert svc.consume_llm(_USER, 1) is True

    def test_the_timezone_is_resolved_from_the_user_record(self, svc):
        """Every surface must agree on the day key, so no caller supplies it."""
        self._user_in('Asia/Tokyo')
        with _at(datetime(2026, 3, 23, 20, 0, tzinfo=timezone.utc)):  # 24 Mar in Tokyo
            svc.consume_llm(_USER, 1)
        assert usage_collection().find_one({'telegram_id': _USER})['day'] == '2026-03-24'

    def test_an_explicit_timezone_matches_the_looked_up_one(self, svc):
        """The scheduler passes the timezone it already holds; it must not
        produce a different key from the lookup every other caller does."""
        self._user_in('Asia/Tokyo')
        with _at(datetime(2026, 3, 23, 20, 0, tzinfo=timezone.utc)):
            svc.consume_llm(_USER, 1, 'Asia/Tokyo')
            svc.consume_llm(_USER, 1)
            assert svc.used_today(_USER) == 2
        assert len(list(usage_collection().find({'telegram_id': _USER}))) == 1

    def test_an_unknown_user_falls_back_to_utc(self, svc):
        with _at(datetime(2026, 3, 23, 20, 0, tzinfo=timezone.utc)):
            svc.consume_llm(_USER, 1)
        assert usage_collection().find_one({'telegram_id': _USER})['day'] == '2026-03-23'

    def test_an_unusable_timezone_falls_back_to_utc(self, svc):
        """Unlike a scheduled send, guessing here shifts a window and wakes nobody."""
        self._user_in('Invalid/Zone')
        with _at(datetime(2026, 3, 23, 20, 0, tzinfo=timezone.utc)):
            assert svc.consume_llm(_USER, 1) is True
        assert usage_collection().find_one({'telegram_id': _USER})['day'] == '2026-03-23'


class TestStorage:
    def test_used_today_is_zero_before_anything_is_spent(self, svc):
        assert svc.used_today(_USER) == 0

    def test_one_document_per_user_per_day(self, svc):
        svc.consume_llm(_USER, 1)
        svc.consume_llm(_USER, 1)
        assert len(list(usage_collection().find({'telegram_id': _USER}))) == 1

    def test_a_ttl_index_is_created_on_first_write(self, svc):
        svc.consume_llm(_USER, 1)
        ttl = [
            spec for spec in usage_collection().index_information().values()
            if spec.get('expireAfterSeconds') is not None
        ]
        assert ttl and ttl[0]['expireAfterSeconds'] == USAGE_RETENTION_DAYS * 24 * 60 * 60

    def test_delete_for_user_removes_only_that_user(self, svc):
        svc.consume_llm(_USER, 1)
        svc.consume_llm(99, 1)
        assert UsageRepository().delete_for_user(_USER) == 1
        assert [d['telegram_id'] for d in usage_collection().find()] == [99]


class TestMeteringFailures:
    """A metering outage must not become a user-visible failure.

    `consume_llm` answers "no" instead of raising, which is fail-closed for
    Anthropic — spend that cannot be metered is not incurred — and leaves every
    caller on the degradation path it already has written and tested. The
    alternative is an exception thrown past that path into a generic apology.
    """

    def test_a_counter_failure_refuses_rather_than_raises(self, svc):
        with patch.object(svc._repo, 'increment', side_effect=RuntimeError('mongo is down')):
            assert svc.consume_llm(_USER) is False

    def test_a_timezone_lookup_failure_refuses_rather_than_raises(self, svc):
        """The day key needs the user record, which is a second thing that can fail."""
        with patch.object(svc._users, 'find', side_effect=RuntimeError('mongo is down')):
            assert svc.consume_llm(_USER) is False

    def test_the_failure_is_logged(self, svc, caplog):
        with patch.object(svc._repo, 'increment', side_effect=RuntimeError('mongo is down')):
            svc.consume_llm(_USER)
        assert 'meter' in caplog.text.lower()

    def test_a_refund_failure_is_swallowed(self, svc):
        """Callers reach `refund` while already handling an error; raising there
        would replace their failure with a less useful one."""
        with patch.object(svc._repo, 'increment', side_effect=RuntimeError('mongo is down')):
            svc.refund(_USER, 1)  # must not raise


class TestRefund:
    def test_a_refund_returns_the_call_to_the_budget(self, svc):
        svc.consume_llm(_USER, 2)
        svc.refund(_USER, 1)
        assert svc.used_today(_USER) == 1

    def test_a_refunded_call_can_be_spent_again(self, svc):
        svc.consume_llm(_USER, DAILY_LLM_CALL_BUDGET)
        svc.refund(_USER, 1)
        assert svc.consume_llm(_USER, 1) is True

    def test_a_refund_uses_the_same_day_key_as_the_reservation(self, svc):
        """Keyed differently, a refund would credit a day the user never spent."""
        with _at(datetime(2026, 3, 26, 23, 0, tzinfo=timezone.utc)):
            svc.consume_llm(_USER, 2, 'Europe/London')
            svc.refund(_USER, 1, 'Europe/London')
            assert svc.used_today(_USER, 'Europe/London') == 1
