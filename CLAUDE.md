# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This Is

AnxietyJournal — a private Telegram chatbot that helps users externalise and process anxiety through daily check-ins. The bot asks how they're feeling, listens to their response, replies empathetically via LLM, and over time surfaces patterns in their mood and triggers. Written in Python using `python-telegram-bot` v20+ (async), calling Claude API for LLM responses, and MongoDB for persistence.

## Commands

```bash
# Run the bot
python main.py

# Via Docker
docker-compose up

# Lint / format
flake8
black .

# Run tests (Python 3.11+; runtime deps are in requirements.txt)
python -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
.venv/bin/pytest
```

## Architecture

```
User (Telegram) → Handlers → Services → LLM / DB
```

**Entry point**: `main.py` — builds the Telegram `Application`, registers handlers, calls `run_polling()`.

**Async rule**: handlers and scheduler callbacks are coroutines sharing one event loop. The services stay
synchronous, so every call into them from a handler or the scheduler tick goes through `asyncio.to_thread`.
A blocking Anthropic or pymongo call left on the loop stalls the bot for every user, not just the caller.
This keeps the loop responsive; it does not make updates concurrent. Updates are still processed one at a time.

**Conversation flow** (`bot/handlers/journal/`):

- `ONBOARDING_NAME` → `ONBOARDING_TIMEZONE` → `ONBOARDING_TIME` → `ONBOARDING_THERAPY`: first-time setup (`onboarding.py`). The account is written with `onboarded=True` at the reminder-time step, so the optional cohort question that follows can be abandoned without leaving a half-created user
- `MAIN_MENU`: persistent menu (Check In, History, Stats, Weekly Summary, Export, Help) — `menu.py`
- `CHECK_IN_MOOD`: user rates mood 1–10 — `checkin.py`
- `CHECK_IN_TEXT`: user writes journal entry → LLM extracts tags, generates empathetic response → entry saved → streak updated — `checkin.py`
- `CHECK_IN_GUIDANCE_OFFER`: on a low mood score, an opt-in offer of coping guidance — `checkin.py`
- `DELETE_CONFIRM`: `/delete` waits here for the exact confirmation button — `account.py`

`/export` and `/flag` (`export.py`) are single-step commands that return to `MAIN_MENU`.

**Routing.** Every command is listed both as an entry point and as a fallback, and `allow_reentry` is
off. Do not turn it back on. Re-entry checks the entry points *before* the current state's handlers,
and the last entry point, `recover_state`, matches any text. With re-entry on, every mood rating,
journal entry, and onboarding answer went to recovery. `tests/test_routing.py` drives the real
`ConversationHandler.check_update`, because handler tests that call callbacks directly cannot see this.

`bot/handlers/journal/__init__.py` is a thin orchestrator: the `ConversationHandler` wiring and
`register()`. Each responsibility lives in its own module — `states.py` (state ints and mood
thresholds), `deps.py` (service singletons, reached as `deps.llm_svc` etc.), `errors.py`
(`@service_errors`, the shared "fall back to main menu" decorator), `timezones.py` (IANA lookup),
the read-only `views.py` (history, stats, weekly summary), `export.py` (`/export`, `/flag`) and
`account.py` (`/delete`).

**Layers**:
| Directory | Role |
|---|---|
| `bot/handlers/` | Telegram command and conversation handlers |
| `bot/keyboards.py` | ReplyKeyboard definitions (main menu, mood 1–10) |
| `services/` | Business logic — `LlmService`, `UserService`, `JournalService`, `SchedulerService`, `AnalyticsService`, `UsageService`, `ExportService`, `AccountService` |
| `services/safety.py` | `detect_crisis` — the deterministic crisis lexicon. Pure: no DB, no network, no LLM |
| `services/tags.py` | Tag normalisation and the canonical tag vocabulary. Pure |
| `repositories/` | MongoDB data access — `UserRepository`, `EntryRepository`, `StreakRepository`, `EventRepository`, `UsageRepository`, `NotificationRepository`, `ConversationRepository` |
| `db/db.py` | MongoDB connection and collection accessors |
| `bot/persistence.py` | MongoDB-backed `BasePersistence` — conversation state and an allowlisted slice of `user_data` |
| `messages/strings.py` | All user-facing message templates |
| `messages/markdown.py` | `escape_md` — Markdown v1 escaping, shared by `bot/` and `services/` |

**LLM integration** (`LlmService`):

- `get_empathetic_response(mood_score, entry_text)` — 2-3 paragraph empathetic reply
- `extract_tags(entry_text)` — up to 5 normalised theme tags; `[]` when the call fails (see below)
- `get_weekly_summary(entries)` — weekly pattern summary (Phase 4)
- Model is configured via `ANTHROPIC_MODEL` (default `claude-3-5-sonnet-latest`), `max_tokens=512`

`_call` answers a failed request with `FALLBACK_REPLY`, which is prose meant for a person to read.
Anything stored as data must use `_complete`, which returns `None` on failure instead. Before this
split, every Anthropic outage saved the apology as an entry's tags.

**Tags** (`services/tags.py`): cleaning, a canonical vocabulary with variants, plural folding into
that vocabulary only, and rejection of anything that isn't tag-shaped. It is idempotent and runs
twice: at extraction, and in `top_tags`/`tag_counts` wherever tags are counted. Stored tags are
therefore always read through the current vocabulary, so revising the vocabulary needs no backfill.
The vocabulary is a first cut, to be revised against real tag data.

**Export** (`ExportService`, `/export`): the last `EXPORT_DAYS` (30) local days as a Markdown document.
It is deliberately rough v0, meant to test whether users bring it into therapy. It makes no LLM call,
so there is no budget cost, no outage path, and no text the user didn't write. Entries flagged with
`/flag` (`flagged_for_session`, latest entry only) are listed first.

**Streak logic** (`JournalService._update_streak`): increments if last check-in was yesterday, resets to 1 if gap > 1 day, no-ops if already checked in today.

**Scheduler** (`SchedulerService`): a 60-second repeating tick decides *who* is due and schedules a
one-shot `run_once` job per user per task — nothing is sent, and no LLM is called, from the tick
itself. A user is due for a 30-minute window after their local `reminder_time` (`_DUE_WINDOW_MINUTES`)
rather than on an exact minute match, so a deploy or reboot cannot silently drop a day's reminder.
The window means a user stays due for ~30 consecutive ticks, so every send is guarded twice: an
in-process `_inflight` set covers the gap before the watermark is written, and three per-user date
watermarks — `last_reminder_sent`, `last_weekly_summary_sent`, `last_weekly_summary_check` — close
the window for the rest of the local day and survive a restart. `last_weekly_summary_check` exists
because the "too few entries this week" outcome writes no `_sent` watermark and would otherwise
re-scan on every tick. A job that raises writes no watermark, so the next tick retries it; the
window bounds those retries. Unlike `time_utils.resolve_timezone`, an unusable timezone here
suppresses the send rather than falling back to UTC.

**Safety** (`services/safety.py`, `checkin.py`): crisis resources are triggered by two independent
signals — a mood score at or below `CRISIS_MOOD_THRESHOLD`, and `detect_crisis` matching the entry
text against a fixed keyword lexicon. The lexicon is deliberately **never** an LLM call: `LlmService._call`
swallows every exception and returns fallback prose, so a model-backed classifier would fail *open*
during an Anthropic outage. It is also deliberately over-inclusive — no negation handling, so "I don't
want to kill myself" matches — because a false positive costs an extra block of hotline numbers while
a false negative costs the thing this exists to prevent. Resources are sent before the `try` block,
once per entry regardless of how many triggers fired, and a content match opens the guidance offer at
any mood score.

**Instrumentation** (`AnalyticsService`): one append-only `events` collection, event names defined as
constants at the top of `services/analytics_service.py`. Two rules: tracking **never raises** (a failed
insert must not cost a user their check-in) and events **never carry entry text**. What upholds the
second rule is the call sites: every prop is a scalar or a closed-vocabulary label. `_scrub` is a
backstop beneath them, not the guarantee — it drops over-long strings wherever they sit, including
inside lists and dicts, which catches `text=` passed where `text_length=` was meant, but cannot catch
a three-word entry. Adding a prop means checking it by eye. A TTL index expires events after
`EVENT_RETENTION_DAYS`.

**LLM spend ceiling** (`UsageService`): `DAILY_LLM_CALL_BUDGET` Anthropic calls per user per local day,
reserved *before* the work so overlapping requests cannot both pass the check, and handed back via
`refund` when refused or when reserved work never ran, so the counter stays close to a record of calls
actually made. `UsageService` resolves the user's timezone itself rather than taking it as an argument —
if one surface keyed the day on UTC and another on local time, a user would hold two counters across
midnight and get twice the budget. `consume_llm` **never raises**: a metering outage answers "no", which
is fail-closed for Anthropic (spend that cannot be metered is not incurred) and leaves every caller on
its normal degradation path, which is open for the user — the entry is still saved, the mood trend still
renders, and the guidance path falls back to a fixed grounding exercise.

**Conversation state ints are an on-disk format.** `MongoPersistence` writes the raw value into
`ptb_conversations`, so a new state in `states.py` may only be *appended*. Inserting one in the middle
silently reinterprets every stored row after it — on the deploy that ships the change, a user resting on
the main menu comes back as mid-onboarding. `tests/test_states.py` pins the values so this fails CI
instead of production.

**PII surfaces and `/delete`** (`AccountService`): `users`, `entries`, `streaks`, `notifications`,
`usage`, `events`, `ptb_user_data` and `ptb_conversations`, deleted in that order. Every step is
attempted, and then `DeletionIncomplete` names any failures; steps are idempotent, so a retry finishes
the job. **A new collection must join the fan-out.** `tests/test_account_service.py` fails if any
accessor in `db/db.py` is missing, and it scans the whole database for the id after a real-path seed.
The handler also clears in-memory `user_data` (PTB would otherwise write it back on the next flush)
and returns `END`, which removes the stored conversation state. Writes that are bookkeeping about a
user, like the scheduler watermarks, use the non-upserting `UserService.update`, so a job that is
already running cannot recreate a deleted user. `account_deleted` is tracked with no `telegram_id`.

## Environment Variables (`.env`)

```
TELEGRAM_TOKEN
CLAUDE_API_KEY
MONGODB_URI
ANTHROPIC_MODEL (optional)
```

## Roadmap Status

Phase numbers follow [docs/development-plan.md](docs/development-plan.md), which is the canonical
roadmap and the one the branch names match. [docs/engineering-plan.md](docs/engineering-plan.md) is
the authority on sequencing rationale and implementation traps; where the two disagree, the
engineering plan wins.

- **Phase 0 — Safety and delivery baseline**: complete (CI gate, single Fly instance, crisis hotfix, consent notice)
- **Phase 1 — PTB v13 → v20+ migration**: complete, with the test harness migrated in lockstep
- **Phase 2 — Time correctness and state resilience**: complete (local-day rules, `MongoPersistence`, global error handler)
- **Phase 2a — Database hardening**: not started — boot-time index creation for the existing collections, startup config validation
- **Phase 3 — Scheduler reliability**: complete (due window, watermarks, LLM off the tick)
- **Phase 4 — Deterministic safety and observability**: complete (crisis lexicon, event instrumentation, cohort tagging, LLM spend ceiling)
- **Phase 5 — Data quality and user control**: complete (tag normalisation, fallback-prose tag leak, `/export` v0, `/delete` fan-out, `/flag`), plus a routing fix for in-conversation text
- **Phase 6 — Productize the therapist artifact**: not started
- **Phase 7 — Retention experiments**: blocked on 4–6 weeks of Phase 4 data
