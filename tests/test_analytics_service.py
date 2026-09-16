"""Tests for behavioural instrumentation.

Two properties matter more than any individual event: tracking must never
raise into the caller's flow, and no prop may carry the user's own words. Both
have their own class below.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from db.db import events_collection
from repositories.event_repo import EVENT_RETENTION_DAYS, EventRepository
from services import analytics_service as analytics
from services.analytics_service import AnalyticsService


def _events() -> list:
    return list(events_collection().find({}, {'_id': 0}))


class TestTrack:
    def test_stores_the_event(self):
        AnalyticsService().track(analytics.CHECK_IN_COMPLETED, 42)
        stored = _events()
        assert len(stored) == 1
        assert stored[0]['event'] == 'check_in_completed'
        assert stored[0]['telegram_id'] == 42

    def test_stores_props(self):
        AnalyticsService().track(analytics.CHECK_IN_COMPLETED, 42, mood_score=3, streak=7)
        assert _events()[0]['props'] == {'mood_score': 3, 'streak': 7}

    def test_timestamp_written_is_timezone_aware_utc(self):
        """Stamped as an aware UTC instant, like every other timestamp the bot stores.

        Asserted on the way in rather than on the way out: the driver returns
        naive datetimes unless the client is built with `tz_aware=True`, which
        is the same round-trip `time_utils.as_utc` exists to undo.
        """
        svc = AnalyticsService()
        with patch.object(svc._repo, 'save') as save:
            svc.track(analytics.REMINDER_SENT, 42)
        created = save.call_args.args[0]['created_at']
        assert created.utcoffset() is not None
        assert created.utcoffset().total_seconds() == 0

    def test_telegram_id_may_be_absent(self):
        """A job or a failure with no update behind it still deserves an event."""
        AnalyticsService().track(analytics.HANDLER_ERROR)
        assert _events()[0]['telegram_id'] is None

    def test_events_accumulate(self):
        svc = AnalyticsService()
        svc.track(analytics.CHECK_IN_STARTED, 1)
        svc.track(analytics.CHECK_IN_COMPLETED, 1)
        assert [e['event'] for e in _events()] == ['check_in_started', 'check_in_completed']


class TestNeverRaises:
    """A failed insert must cost an analytics row, never a user's check-in."""

    def test_a_broken_repository_does_not_propagate(self):
        svc = AnalyticsService()
        with patch.object(svc._repo, 'save', side_effect=RuntimeError('mongo is down')):
            svc.track(analytics.CHECK_IN_COMPLETED, 42)

    def test_the_failure_is_logged(self, caplog):
        svc = AnalyticsService()
        with patch.object(svc._repo, 'save', side_effect=RuntimeError('mongo is down')):
            svc.track(analytics.CHECK_IN_COMPLETED, 42)
        assert 'check_in_completed' in caplog.text


class TestPropScrubbing:
    def test_a_long_string_prop_is_dropped(self):
        """The guard against a future call site passing the entry itself."""
        AnalyticsService().track(analytics.CHECK_IN_COMPLETED, 42, text='x' * 500)
        assert _events()[0]['props'] == {}

    def test_dropping_a_prop_keeps_the_event(self):
        AnalyticsService().track(analytics.CHECK_IN_COMPLETED, 42, text='x' * 500, mood_score=2)
        assert _events()[0]['props'] == {'mood_score': 2}

    def test_short_labels_survive(self):
        AnalyticsService().track(analytics.LLM_BUDGET_EXCEEDED, 42, surface='check_in')
        assert _events()[0]['props'] == {'surface': 'check_in'}

    def test_non_string_props_are_untouched(self):
        AnalyticsService().track(analytics.CRISIS_RESOURCES_SHOWN, 42, categories=['self_harm'], count=3)
        assert _events()[0]['props'] == {'categories': ['self_harm'], 'count': 3}

    def test_the_drop_is_logged(self, caplog):
        AnalyticsService().track(analytics.CHECK_IN_COMPLETED, 42, text='x' * 500)
        assert 'text' in caplog.text


class TestReadBack:
    def test_recent_for_user_is_scoped_to_that_user(self):
        svc = AnalyticsService()
        svc.track(analytics.CHECK_IN_STARTED, 1)
        svc.track(analytics.CHECK_IN_COMPLETED, 1)
        svc.track(analytics.CHECK_IN_STARTED, 2)
        assert {e['event'] for e in svc.recent_for_user(1)} == {'check_in_started', 'check_in_completed'}
        assert len(svc.recent_for_user(2)) == 1

    def test_recent_for_user_is_newest_first(self):
        """Written through the repository so the timestamps are distinguishable —
        two `track` calls in a row land in the same millisecond and have no order."""
        repo = EventRepository()
        now = datetime.now(timezone.utc)
        for days_ago in (1, 3, 2):
            repo.save({
                'event': f'day_{days_ago}',
                'telegram_id': 1,
                'created_at': now - timedelta(days=days_ago),
                'props': {},
            })
        assert [e['event'] for e in AnalyticsService().recent_for_user(1)] == ['day_1', 'day_2', 'day_3']

    def test_recent_for_user_respects_the_limit(self):
        svc = AnalyticsService()
        for _ in range(5):
            svc.track(analytics.CHECK_IN_STARTED, 1)
        assert len(svc.recent_for_user(1, limit=2)) == 2


class TestRetentionAndDeletion:
    def test_a_ttl_index_is_created_on_first_write(self):
        """Retention is a property of the database, not of a cleanup script."""
        EventRepository().save({'event': 'x', 'telegram_id': 1, 'created_at': None, 'props': {}})
        ttl = [
            spec for spec in events_collection().index_information().values()
            if spec.get('expireAfterSeconds') is not None
        ]
        assert ttl and ttl[0]['expireAfterSeconds'] == EVENT_RETENTION_DAYS * 24 * 60 * 60

    def test_events_past_the_retention_window_are_gone(self):
        """The TTL index does the forgetting — nothing has to remember to."""
        repo = EventRepository()
        stale = datetime.now(timezone.utc) - timedelta(days=EVENT_RETENTION_DAYS + 1)
        repo.save({'event': 'stale', 'telegram_id': 1, 'created_at': stale, 'props': {}})
        assert repo.find_recent(1) == []

    def test_delete_for_user_removes_only_that_user(self):
        """The /delete fan-out reaches this collection too."""
        svc = AnalyticsService()
        svc.track(analytics.CHECK_IN_STARTED, 1)
        svc.track(analytics.CHECK_IN_STARTED, 2)
        assert EventRepository().delete_for_user(1) == 1
        assert [e['telegram_id'] for e in _events()] == [2]


class TestTaxonomy:
    def test_every_event_name_is_unique(self):
        """A copy-pasted constant would silently merge two behaviours into one."""
        names = [
            value for key, value in vars(analytics).items()
            if key.isupper() and isinstance(value, str) and not key.startswith('_')
        ]
        assert len(names) == len(set(names))


class TestNestedPropScrubbing:
    """`triggers` and `categories` are lists, so the guard has to look inside them.

    A cap applied only to top-level strings would wave through the same prose one
    layer down, which is exactly where the call sites in this codebase put their
    string props.
    """

    def test_prose_inside_a_list_is_dropped(self):
        AnalyticsService().track(analytics.CRISIS_RESOURCES_SHOWN, 42, categories=['x' * 500])
        assert _events()[0]['props'] == {}

    def test_a_list_keeps_its_labels_and_loses_only_the_prose(self):
        AnalyticsService().track(
            analytics.CRISIS_RESOURCES_SHOWN, 42, categories=['self_harm', 'y' * 500]
        )
        assert _events()[0]['props'] == {'categories': ['self_harm']}

    def test_prose_inside_a_dict_is_dropped(self):
        AnalyticsService().track(analytics.CHECK_IN_COMPLETED, 42, detail={'text': 'x' * 500})
        assert _events()[0]['props'] == {}

    def test_a_dict_keeps_its_scalars(self):
        AnalyticsService().track(
            analytics.CHECK_IN_COMPLETED, 42, detail={'text': 'x' * 500, 'mood_score': 3}
        )
        assert _events()[0]['props'] == {'detail': {'mood_score': 3}}

    def test_an_empty_container_is_preserved(self):
        """`categories: []` means "nothing matched" and has to survive as itself —
        it is only dropped when scrubbing is what emptied it."""
        AnalyticsService().track(analytics.CRISIS_RESOURCES_SHOWN, 42, categories=[])
        assert _events()[0]['props'] == {'categories': []}

    def test_a_tuple_is_stored_as_a_list(self):
        """`detect_crisis` returns a tuple; BSON has no tuple type."""
        AnalyticsService().track(analytics.CRISIS_RESOURCES_SHOWN, 42, categories=('self_harm',))
        assert _events()[0]['props'] == {'categories': ['self_harm']}


class TestWhatTheGuardCannotDo:
    def test_a_short_entry_is_not_caught(self):
        """Recorded deliberately: nothing about the length of a terse entry
        distinguishes it from a label, so `_scrub` cannot be the guarantee that
        events carry no entry text. The call sites are — this is the net under
        them. If this test ever needs changing, the fix is a prop allowlist, not
        a smaller cap.
        """
        AnalyticsService().track(analytics.CHECK_IN_COMPLETED, 42, text='I feel awful')
        assert _events()[0]['props'] == {'text': 'I feel awful'}

    def test_no_call_site_passes_free_text_today(self):
        """The invariant the guard cannot enforce, asserted where it is upheld:
        every prop in the taxonomy is a scalar or a closed-vocabulary label."""
        import ast
        import pathlib

        offenders = []
        for path in pathlib.Path('.').glob('**/*.py'):
            if 'tests' in path.parts or '.venv' in path.parts:
                continue
            tree = ast.parse(path.read_text())
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                target = node.func.attr if isinstance(node.func, ast.Attribute) else None
                if target != 'track':
                    continue
                for kw in node.keywords:
                    # A prop built from the entry text itself. `len(text)` is
                    # fine; `text` is not.
                    if isinstance(kw.value, ast.Name) and kw.value.id in ('text', 'entry_text'):
                        offenders.append(f'{path}: {kw.arg}={kw.value.id}')
        assert offenders == []
