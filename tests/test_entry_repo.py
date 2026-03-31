"""Tests for EntryRepository — MongoDB read/write operations."""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from repositories.entry_repo import EntryRepository

USER = 222222
OTHER = 333333


@pytest.fixture
def repo():
    return EntryRepository()


def _entry(mood: int, text: str, created_at: datetime | None = None, user: int = USER) -> dict:
    return {
        'telegram_id': user,
        'mood_score': mood,
        'text': text,
        'tags': [],
        'created_at': created_at or datetime.utcnow(),
    }


class TestSaveAndCount:
    def test_count_starts_at_zero(self, repo):
        assert repo.count(USER) == 0

    def test_count_increments_per_save(self, repo):
        repo.save(_entry(7, "first"))
        repo.save(_entry(5, "second"))
        assert repo.count(USER) == 2

    def test_count_is_user_scoped(self, repo):
        repo.save(_entry(7, "mine"))
        repo.save(_entry(5, "theirs", user=OTHER))
        assert repo.count(USER) == 1
        assert repo.count(OTHER) == 1


class TestFindRecent:
    def test_returns_newest_first(self, repo):
        older = datetime(2026, 3, 25, 10, 0)
        newer = datetime(2026, 3, 27, 10, 0)
        repo.save(_entry(4, "older", older))
        repo.save(_entry(8, "newer", newer))
        results = repo.find_recent(USER, limit=2)
        assert results[0]['text'] == "newer"
        assert results[1]['text'] == "older"

    def test_respects_limit(self, repo):
        for i in range(5):
            repo.save(_entry(5, f"entry {i}"))
        assert len(repo.find_recent(USER, limit=3)) == 3

    def test_empty_returns_empty_list(self, repo):
        assert repo.find_recent(USER) == []

    def test_is_user_scoped(self, repo):
        repo.save(_entry(7, "mine"))
        repo.save(_entry(5, "theirs", user=OTHER))
        results = repo.find_recent(USER)
        assert len(results) == 1
        assert results[0]['text'] == "mine"


class TestFindSince:
    def test_returns_entries_on_or_after_since(self, repo):
        now = datetime.utcnow()
        repo.save(_entry(5, "recent", now))
        repo.save(_entry(4, "old", now - timedelta(days=10)))
        results = repo.find_since(USER, now - timedelta(days=1))
        assert len(results) == 1
        assert results[0]['text'] == "recent"

    def test_returns_entries_in_ascending_order(self, repo):
        now = datetime.utcnow()
        repo.save(_entry(7, "later", now))
        repo.save(_entry(3, "earlier", now - timedelta(days=2)))
        results = repo.find_since(USER, now - timedelta(days=3))
        assert results[0]['text'] == "earlier"
        assert results[1]['text'] == "later"

    def test_returns_empty_when_no_entries_in_range(self, repo):
        now = datetime.utcnow()
        repo.save(_entry(5, "old", now - timedelta(days=10)))
        assert repo.find_since(USER, now - timedelta(days=1)) == []

    def test_is_user_scoped(self, repo):
        now = datetime.utcnow()
        repo.save(_entry(7, "mine"))
        repo.save(_entry(5, "theirs", user=OTHER))
        results = repo.find_since(USER, now - timedelta(hours=1))
        assert len(results) == 1
        assert results[0]['text'] == "mine"

    def test_empty_repo_returns_empty_list(self, repo):
        assert repo.find_since(USER, datetime.utcnow() - timedelta(days=7)) == []


class TestAverageMood:
    def test_average_of_multiple_entries(self, repo):
        repo.save(_entry(6, "a"))
        repo.save(_entry(8, "b"))
        repo.save(_entry(4, "c"))
        assert repo.average_mood(USER) == 6.0

    def test_single_entry(self, repo):
        repo.save(_entry(7, "only"))
        assert repo.average_mood(USER) == 7.0

    def test_no_entries_returns_zero(self, repo):
        assert repo.average_mood(USER) == 0.0

    def test_rounds_to_one_decimal(self, repo):
        repo.save(_entry(7, "a"))
        repo.save(_entry(8, "b"))  # avg = 7.5
        assert repo.average_mood(USER) == 7.5
