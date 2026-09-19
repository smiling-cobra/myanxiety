# Development Plan

This file is the concise phase summary of [engineering-plan.md](engineering-plan.md). The engineering plan is the canonical source for sequencing rationale, detailed risks, and implementation traps; this document should stay shorter and mirror the same phase boundaries and ordering.

If this file and [engineering-plan.md](engineering-plan.md) ever disagree, follow the engineering plan and update this summary in the same change.

This plan assumes two product decisions from the attached analysis are locked:

- The primary wedge is a therapist-shareable export for in-therapy users.
- Existing MongoDB data can be dropped if schema changes require it.

The sequence below is intentionally aligned to [engineering-plan.md](engineering-plan.md). Safety and operational hardening come first, the Telegram framework migration happens as one forced transition, and product-facing expansion only starts after time correctness, scheduler reliability, and data quality are stable.

## Phase 0: Safety and delivery baseline

Stabilize the product before larger refactors. Add a CI gate for `pytest` and `flake8`, move Fly deployment to a single instance with an immediate deploy strategy, and ship the safety fixes that are small enough to survive later migration work unchanged.

This phase should include fail-closed handling when `mood_score` is missing, crisis-resource availability on acute low-mood paths even when guidance is declined or another step fails, a clear consent/privacy disclosure in onboarding and help copy, and cleanup of dead or misleading leftover code.

Primary anchors:

- [main.py](../main.py)
- [bot/handlers/journal.py](../bot/handlers/journal.py)
- [messages/strings.py](../messages/strings.py)
- [fly.toml](../fly.toml)

## Phase 1: Migrate `python-telegram-bot` v13 to v20+

Treat the Telegram upgrade as a single migration branch. Replace `Updater` and `Dispatcher` with `Application`, update handler registration and the `Filters` to `filters` API, and convert Telegram handlers and scheduled send paths to async.

The migration must include event-loop protection. The current Anthropic and MongoDB calls are synchronous. Under v20+, slow LLM or DB calls can freeze the whole bot unless they are moved off the event loop with `asyncio.to_thread` or replaced with async clients, and Mongo connection timeouts must be explicit.

Primary anchors:

- [main.py](../main.py)
- [bot/handlers/journal.py](../bot/handlers/journal.py)
- [bot/handlers/commands.py](../bot/handlers/commands.py)
- [services/scheduler_service.py](../services/scheduler_service.py)
- [services/llm_service.py](../services/llm_service.py)
- [db/db.py](../db/db.py)
- [requirements.txt](../requirements.txt)

## Phase 1a: Migrate the test harness in lockstep

Update the tests alongside the framework migration, not after it. Convert handler and scheduler tests to async, replace synchronous mocks with `AsyncMock` where Telegram replies or bot sends are awaited, and add `pytest-asyncio`.

Keep the current direct-function testing style. It already covers most behavior at the right level and avoids widening the migration scope into dispatcher-driven integration tests.

Primary anchors:

- [tests/test_handlers.py](../tests/test_handlers.py)
- [tests/test_scheduler_service.py](../tests/test_scheduler_service.py)
- [tests/test_journal_service.py](../tests/test_journal_service.py)
- [pytest.ini](../pytest.ini)

## Phase 2: Time correctness and state resilience

Align day-based behavior to the user’s timezone. Entries can remain stored in UTC, but streaks, reminder windows, and weekly windows should be computed against local user time so check-ins around midnight do not produce UTC-based logic errors.

In the same phase, add minimal conversation-state persistence for onboarding progress, Telegram conversation state, `name`, and `mood_score`. Do not persist raw `entry_text` outside the primary entries collection, because that duplicates sensitive free text into a second PII surface.

Pair this with a global error handler and a safe fallback that can re-anchor users to the main menu after state loss or unexpected handler exceptions.

Primary anchors:

- [services/journal_service.py](../services/journal_service.py)
- [services/user_service.py](../services/user_service.py)
- [repositories/user_repo.py](../repositories/user_repo.py)
- [main.py](../main.py)

## Phase 2a: Database hardening

Add boot-time index creation for the main query paths and explicit startup validation for required configuration. This is small work but high leverage: it improves query behavior, avoids silent slow paths, and makes broken deploys fail clearly.

Recommended indexes include user lookup and onboarding scans, user-scoped entry queries by timestamp, and streak lookup by user.

_Status: complete. `db/indexes.py` creates the per-user indexes at boot: `users.telegram_id` and `streaks.telegram_id` (both unique), `users.onboarded`, `entries.{telegram_id, created_at}`, `notifications.telegram_id` and `ptb_conversations.{name, key}`. An unreachable database fails the boot. An index that can't be built is logged and skipped, since the bot still works without it. `config.py` checks the required environment variables before anything else loads, and names every missing one. Before the first deploy, check production for duplicate `telegram_id` rows in `users` and `streaks`. The unique indexes won't build over them._

Primary anchors:

- [db/db.py](../db/db.py)
- [repositories/user_repo.py](../repositories/user_repo.py)
- [repositories/entry_repo.py](../repositories/entry_repo.py)
- [repositories/streak_repo.py](../repositories/streak_repo.py)

## Phase 3: Scheduler reliability and duplicate suppression

Replace the exact-minute due check with a bounded due window, but do not ship that alone. The window change must land together with per-user send watermarks for both reminders and weekly summaries, or the bot will double-send within the window.

After that, remove expensive LLM work from the repeating global scheduler tick. The scheduler should decide who is due, and summary generation or other heavy work should be deferred per user rather than performed inline in the global loop.

Primary anchor:

- [services/scheduler_service.py](../services/scheduler_service.py)

## Phase 4: Deterministic safety and observability

Add content-triggered crisis detection using a deterministic lexicon over entry text. Do not use the LLM as the safety gate, because the current LLM layer degrades by swallowing exceptions and returning fallback prose, which would fail open for crisis classification.

At the same time, add instrumentation for onboarding completion, reminder delivery, check-in completion, low-mood guidance uptake, weekly summary sends, export usage, and per-user LLM usage or cost boundaries. If cohort fields such as acquisition source or “currently in therapy” matter, they must ship here because they cannot be reconstructed later.

Primary anchors:

- [bot/handlers/journal.py](../bot/handlers/journal.py)
- [services/llm_service.py](../services/llm_service.py)
- [messages/strings.py](../messages/strings.py)

## Phase 5: Data quality and user control surfaces

Normalize extracted tags so stats and exports stay readable and so different variants of the same concept do not fragment the data set. This phase should also fix the current failure mode where fallback LLM prose can leak into saved tags during provider outages.

Then ship two user-control surfaces: a basic therapist-shareable export and a complete delete flow. The first export should be deliberately rough but useful, likely plain Markdown or text. The immediate goal is to test whether users actually bring it into therapy, not to perfect formatting.

The delete flow must enumerate every PII-bearing location, including any future conversation-persistence store, not just the current user, entry, and streak collections.

As of Phase 4 that list is: `users`, `entries`, `streaks`, `notifications`, `ptb_conversations`, `ptb_user_data`, `events`, and `usage`. `EventRepository.delete_for_user` and `UsageRepository.delete_for_user` already exist for the last two.

_Status: complete. `services/account_service.py` holds the fan-out, and `tests/test_account_service.py` fails if a collection accessor in `db/db.py` is left out of it. `/export` ships as a Markdown document of the last 30 local days, and `/flag` marks the latest entry to raise in session._

Optional adjacent feature: add a lightweight “flag for session” marker on entries if you want one small feature that directly improves the therapist-sharing workflow without expanding into clinician tooling.

Primary anchors:

- [services/llm_service.py](../services/llm_service.py)
- [repositories/entry_repo.py](../repositories/entry_repo.py)
- [repositories/user_repo.py](../repositories/user_repo.py)
- [repositories/streak_repo.py](../repositories/streak_repo.py)
- [messages/strings.py](../messages/strings.py)

## Phase 6: Productize the therapist artifact

Once export v0 exists and the tag corpus is cleaner, improve the export into a clinician-readable artifact with clear structure, strong signal-to-noise, and a ninety-second reading target. After that, rework onboarding and in-product copy so privacy boundaries, export value, and intended use are explicit from first run.

This phase should be informed by real usage rather than assumptions. It depends on instrumentation, clean tags, and early export behavior already being in place.

_Status: complete, as a first cut. The export now opens with a brief meant to be read in about ninety seconds (flagged items, days written, mood, themes with their average mood, lowest points, mood by day), followed by the entries in full, grouped by day. Onboarding and help text say what the bot is for and what the export contains. Alongside this, the first entry of a local day is the daily check-in, and later entries that day are notes: same safety path, no LLM reply. Users who have already checked in get no reminder. The therapist conversations in [engineering-plan.md](engineering-plan.md) §8 have not happened yet, and should shape the next revision of the layout._

Primary anchors:

- [messages/strings.py](../messages/strings.py)
- [bot/handlers/journal.py](../bot/handlers/journal.py)
- [docs/bot-analysis.md](bot-analysis.md)
- [docs/engineering-plan.md](engineering-plan.md)

## Phase 7: Retention experiments after baseline data exists

Do not redesign retention before there is enough instrumentation data to evaluate tradeoffs. The current streak mechanic may drive guilt more than value, but replacing it without baseline behavior data is guesswork.

After at least four to six weeks of instrumented usage, choose between softer reminder loops, therapist-session-oriented prompts, or non-streak progress markers based on observed behavior rather than intuition.

## Verification strategy

Use the existing test suite as the primary regression harness, especially:

- [tests/test_handlers.py](../tests/test_handlers.py)
- [tests/test_scheduler_service.py](../tests/test_scheduler_service.py)
- [tests/test_journal_service.py](../tests/test_journal_service.py)
- [tests/test_llm_service.py](../tests/test_llm_service.py)

Critical manual checks after implementation phases:

1. Verify the pre-migration baseline with `pytest` and `flake8`.
2. Validate local-midnight streak behavior after time-correctness changes.
3. Validate reminder and weekly-summary delivery across at least two timezones after scheduler changes.
4. Add deterministic crisis-detection tests covering both low and non-low numeric mood scores.
5. Confirm tag normalization preserves readable stats and export output.
6. Confirm delete removes all user-linked state and records.

## Scope decisions

Included in this plan:

- Safety fixes
- PTB migration and async hardening
- Time correctness
- Minimal conversation-state persistence
- Scheduler reliability
- Deterministic crisis detection
- Instrumentation and cohort tagging
- Tag cleanup
- Export and delete surfaces
- Onboarding and copy improvements

Explicitly out of scope for now:

- Clinician accounts or dashboards
- Multi-user admin tooling
- Data migration
- Internationalization
- Monetization work

## Open recommendations

Two decisions are still worth making explicit:

1. Crisis resources are not jurisdiction-aware yet. Recommendation: defer localization until deterministic content-triggered safety is in place.
2. For the PTB migration, prefer `asyncio.to_thread` as the first protection step for Anthropic calls. Moving fully to an async LLM client is cleaner long term, but it broadens the migration surface.
