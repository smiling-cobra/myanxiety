# Engineering Plan — AnxietyJournal

_Written 2026-09-11. Companion to [bot-analysis.md](bot-analysis.md), which holds the product rationale; this file holds the canonical sequencing, rationale, and implementation traps. The concise phase summary lives in [development-plan.md](development-plan.md) and should mirror this file's phase boundaries and ordering._

All claims below are anchored to `file:line` so they stay checkable as the code moves. Where a line reference no longer matches, trust the code.

If this file and [development-plan.md](development-plan.md) ever disagree, treat this file as authoritative and update the summary in the same change.

## 1. Context and decisions

The product analysis concluded that the viable shape is **this distribution mechanism + one defined population + the longitudinal data asset** — not "a private Telegram bot for anxiety journaling," which is a commodity.

Three decisions are locked and this plan assumes them:

- **No data migration.** MongoDB holds only the owner's test data. Existing records can be dropped rather than migrated.
- **Migrate to python-telegram-bot v20+.** v13 is end-of-life and synchronous, and is the direct cause of the scheduler blocking on LLM calls.
- **Target population: in-therapy consumers.** Direct-to-consumer marketing aimed at people already seeing a therapist. The client is both the user and the buyer. The headline feature is an export a client can show their therapist.

**Explicitly out of scope:** clinician-facing accounts, multi-client dashboards, and audit surfaces. Therapists discover the product through their own clients; building for them before that happens is unearned work.

## 2. Sequencing

This ordering is the main contribution of this document, and it is deliberately **not** priority order. Several high-priority items are scheduled late because doing them early means doing them twice.

```
Week 0 — pre-work, all on v13, all small, all independently shippable
  P1  CI gate: run pytest + flake8 on PR          prerequisite for everything
  P2  Fly single-instance + immediate deploy      migration prerequisite
  P3  Crisis hotfix 3a                            highest severity; jumps the queue
  P4  Consent notice                              legal exposure today
  P5  Dead-code removal                           dup _escape_md, unused import

MIGRATION — v13 to v20+, one branch, big-bang (forced: the versions cannot coexist)

Then, in order
  1   Timezone-correct timestamps + streaks   (+ Mongo indexes, client timeouts)
  7   Persistence + global error handler + lost-state fallback
  2a  Scheduler due-window + per-user watermark
  2b  LLM calls off the scheduler tick
  3b  Content-triggered crisis detection
  4   Instrumentation + cohort tagging
  5   Tag normalisation
  6   /export (crude v0) + /delete
  8   Export artifact, clinician-grade
  9   Onboarding rework
  10  Retention mechanic replacement           schedule-blocked on 4
```

### Why this order

**The migration goes before the timestamp fix.** `services/journal_service.py` and `services/scheduler_service.py` import no telegram symbols, so landing the timestamp work first buys almost no merge-conflict avoidance. Meanwhile the migration is the schedule-dominating unknown — the one item with zero product value and unbounded regression risk. Run it against the current green 143-test baseline so the suite acts as a clean safety net, and discover its true cost in week one rather than week three. Item 1's tests then get written once, under the framework you are actually shipping on.

**Persistence (7) must precede instrumentation (4).** Every deploy wipes conversation state, and deploys are now automatic on every push to `master`. Instrumenting first means measuring your own deploy cadence rather than your users' behaviour.

_(Corrected after Week 0: this originally said CI deploys on every push to `main` with no gate. In fact `fly-deploy.yml` was keyed to a `main` branch that has never existed, so auto-deploy had never once run — deploys were manual. P1 added the gate and the branch name was fixed to `master`, which is what makes the statement above true going forward.)_

**Tag normalisation (5) is a dependency of the export (8)**, not a parallel nicety. Unnormalised free-text tags are precisely what makes a summary illegible to a clinician.

**Item 10 is schedule-blocked, not engineering-blocked.** A streak replacement cannot be evaluated without four to six weeks of baseline data from item 4.

**Ship a crude export in Tier 1, not a polished one in Tier 2.** The core product bet — will a client actually show this to their therapist — sits four dependencies deep (items 1, 5, 6, then 8). A deliberately rough Markdown export at item 6 tests the hypothesis months earlier than a designed one.

## 3. Safety

Called out separately because these are severity issues, not roadmap items. Three distinct defects exist today, in severity order.

### 3.1 `handle_entry_text` swallows failures before the crisis path

`bot/handlers/journal.py:236-258`. A MongoDB failure on a **mood-1** entry hits the `except`, replies `ERROR_GENERIC`, and returns `MAIN_MENU`. The guidance offer at `:252` — and therefore `GUIDANCE_CRISIS_RESOURCES` — is never reached. This needs no user action to trigger. Worth noting `extract_tags` also runs _before_ `save_entry`, so a failure in that path discards the user's entry entirely.

### 3.2 Crisis resources sit behind an opt-in

`bot/handlers/journal.py:363-379`. Pressing anything other than "Yes" returns early, which makes the mood-2 append at `:375` unreachable. A user in acute distress who declines guidance receives `GUIDANCE_DECLINED` and nothing else.

### 3.3 `mood_score` silently defaults to 5

`bot/handlers/journal.py:233` and `:368`. If `user_data` is missing — which happens on every restart, since no persistence is configured — a mood-1 user is re-scored as mood-5, skipping the guidance offer and the crisis path entirely. This must fail closed: re-ask rather than assume.

### Fix 3a — Week 0, small, migration-transparent

- Move the crisis append into `handle_entry_text` **before** the try block, unconditional on all paths once `mood_score` is known.
- Remove the `mood_score` default; re-ask instead.
- Add crisis resources to `HELP_MESSAGE` in `messages/strings.py`.

`/help` is verified reachable mid-conversation: `commands.register` runs at `main.py:30` before `journal.register` at `:31`, both in group 0, so `CommandHandler('help')` wins over the `ConversationHandler`. That gives users an escape hatch that survives the state loss the bot has today.

Carrying cost through the migration is roughly zero — the added `reply_text` becomes an added `await`.

### Fix 3b — post-migration, and deterministic

Content-triggered detection must use a **keyword lexicon, never the LLM**. `LlmService._call` (`services/llm_service.py:79-89`) swallows every exception and returns a fallback string, so an LLM-based classifier **fails open**: an Anthropic outage silently downgrades a crisis to "no crisis," with no log at the decision site.

Any crisis path must fail closed — deterministic match, and when uncertain, show resources. An LLM layer may be added later as an additive signal only, never as the gate.

### Known limitation

`GUIDANCE_CRISIS_RESOURCES` (`messages/strings.py:101-107`) covers an international directory plus US/UK/CA/IE lines. It is not localised by user timezone, and there is no age gate anywhere. Both are real gaps for a consumer product; neither is scheduled here.

## 4. Migration scope

### Test churn is mechanical, not a rewrite

Only **3** telegram imports exist across 1,316 test lines, all `ReplyKeyboardRemove`, all still valid in v20. The suite's discipline — direct function calls, no Dispatcher, no real Telegram objects — pays off exactly here.

| File                              | Tests | Impact                                                                                                                                                                                             |
| --------------------------------- | ----- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `tests/test_entry_repo.py`        | 16    | None from the migration                                                                                                                                                                            |
| `tests/test_journal_service.py`   | 15    | None from the migration                                                                                                                                                                            |
| `tests/test_llm_service.py`       | 13    | None — `LlmService` stays sync                                                                                                                                                                     |
| `tests/test_scheduler_service.py` | 29    | Mechanical: `async def`, `await`, `AsyncMock` on `ctx.bot.send_message`. The `__new__` bypass and the ~22 module-wide `datetime` patches are unaffected                                            |
| `tests/test_handlers.py`          | 70    | Mechanical but touches every test. The `_update()` helper must set `reply_text = AsyncMock()` — `MagicMock`'s auto-created child is sync and awaiting it raises. One helper edit covers most of it |

Add `pytest-asyncio` with `asyncio_mode = "auto"`. Realistically about one day.

### Breaking changes that hit this code

- `main.py:24-38` — `Updater(token, use_context=True)` becomes `Application.builder().token(...).build()`; `updater.dispatcher` is gone; `start_polling()` + `idle()` become `run_polling()`; `use_context` is removed entirely.
- `bot/handlers/journal.py:7-12`, `:399-413` — `Filters` becomes `filters`; `Filters.text` → `filters.TEXT`, `Filters.command` → `filters.COMMAND`, `Filters.location` → `filters.LOCATION`. Nine call sites.
- `dispatcher.add_handler` becomes `application.add_handler` (`journal.py:418`, `commands.py:12`); `register(dispatcher)` signatures rename.
- All ~14 handlers become `async def`; every `reply_text` / `send_message` is awaited, including `scheduler_service.py:39,63`.
- **JobQueue is an optional extra in v20+.** Pinning plain `python-telegram-bot==21.x` leaves `application.job_queue` as `None`, and `SchedulerService().start(None)` raises at boot. Pin `python-telegram-bot[job-queue]`. This is a silent footgun.
- `CallbackContext` survives as an importable type, so handler annotations are low-churn. `ContextTypes.DEFAULT_TYPE` is the idiomatic v20 form; cosmetic.

### The risk that is currently invisible

**Sync I/O on the event loop is a regression the migration introduces.** In v13 the Dispatcher had a worker thread pool, so a slow Anthropic call blocked one worker. v20 has a single event loop — the blocking `anthropic.Anthropic` calls at `journal.py:237,240,373` and `scheduler_service.py:62` will **freeze the bot for every user** for the duration of the call.

Mitigation is mandatory, not optional: wrap every LLM call site in `asyncio.to_thread`, or switch `services/llm_service.py` to `anthropic.AsyncAnthropic`. This is the largest single underestimate in the original plan.

The same reasoning promotes two items from nice-to-have to migration consequence:

- `UserRepository.find_all_onboarded()` (`repositories/user_repo.py:18`) is an unindexed full collection scan running on the event loop every 60 seconds.
- `db/db.py:21` constructs `MongoClient(uri)` with no `serverSelectionTimeoutMS`. The default is 30 seconds, so one MongoDB hiccup becomes 30 seconds of blocked event loop and a bot that appears dead to everyone. One-line fix; do it in the migration PR.

### Staging

Big-bang is forced — v13 and v20 cannot coexist in one environment, so there is no incremental merge path. De-risk around it instead:

- Land **P1** (CI test gate) before opening the branch. Running a mechanical framework rewrite with no automated gate on deploy is the actual risk here, not the migration itself.
- Land **P2** (Fly single-instance) before the branch. A rolling deploy that briefly runs two machines gives two `getUpdates` pollers, which means Telegram 409 conflicts and doubled reminders.
- Structure the branch as five reviewable commits: `main.py` + `register()`; handlers async; scheduler async; tests async; `asyncio.to_thread` + Mongo timeouts.
- Do not pre-abstract handlers behind an async-ready seam. Over-engineering for a one-time change.

**Estimate: 4–8 days** with prior PTB v20 experience; 1.5–2 weeks while learning it.

## 5. Traps and gaps found during verification

**The item-2 double-fire trap.** `_is_weekly_summary_due` gates on `_is_due` (`services/scheduler_service.py:84`), which is exact-minute. Widen that to a due-_window_ and the weekly summary fires on **every tick inside the window**, because `last_weekly_summary_sent` is written only after a successful LLM call and send (`:68-71`), and `_sent_today` guards the reminder path only (`:37`). The watermark must land in the same commit as the window, on both paths. Shipped alone, the window fix is a spam bug.

**`extract_tags` poisons the tag corpus on LLM failure.** `_call` returns `"I'm having trouble responding right now..."`, which `extract_tags` (`services/llm_service.py:36-37`) then splits on commas and stores as a tag. Every Anthropic outage writes a prose sentence into the entry's tag list — corrupting the exact data the normalisation work exists to clean.

**Persistence has a PII coupling.** `user_data` holds `entry_text` (`journal.py:253`), so persisting it writes sensitive free text to a second store, which loops back into consent and `/delete`. Persist the conversation state plus `name` and `mood_score` only, explicitly excluding `entry_text`. Pair this with the fail-closed mood default from 3.3 — otherwise a restart silently re-scores users.

**No MongoDB indexes exist anywhere in the repo.** Needed: `users.telegram_id` (unique), `users.onboarded`, `entries.{telegram_id, created_at}`, `streaks.telegram_id`. One `ensure_indexes()` at boot.

**No global error handler.** `add_error_handler` appears nowhere, so any handler exception outside the four local try/excepts leaves the user in a stuck conversation state with silence. Roughly ten lines, and a prerequisite for item 4 — you cannot instrument failures you never catch. Pair it with a lowest-group `MessageHandler` that re-anchors unrecognised messages to `MAIN_MENU`.

**No startup config validation.** `main.py:19` reads `TELEGRAM_TOKEN` with no check, so a deploy with a missing secret produces a confusing crash-loop instead of a clear error. Fold into the migration PR.

**No LLM rate limit or cost ceiling.** Nothing caps check-ins per user per day, and each one triggers two to three Anthropic calls. The weekly summary sends an entire week's corpus. Spend is unbounded and unmonitored. Fold a per-user daily counter into item 4.

**`/delete` has a fan-out that is easy to half-implement.** Four collections exist — `users`, `entries`, `streaks`, and `notifications` (unused but present) — and persistence will become a fifth location holding user PII. Enumerate them explicitly.

**Unpinned dependencies.** Only `python-telegram-bot` is pinned; `anthropic`, `pymongo` and `timezonefinder` float, and `flake8` / `black` / `pytest` / `mongomock` ship into the production image. Fold the pins and a `requirements-dev.txt` split into the migration PR — you are editing `requirements.txt` regardless. Not a workstream of its own.

**Dockerfile runs as root on the full `python:3.11` image.** Lowest real risk on this list for a single-tenant bot with no untrusted code execution. Bundle opportunistically; do not schedule it.

**The consent gap is an accuracy problem, not only a compliance one.** `ONBOARDING_WELCOME` opens with _"I'm your private anxiety journal"_ (`messages/strings.py:2`) while entry text goes to a third-party API with no disclosure anywhere in the product. For an in-therapy audience this is the likeliest thing to become a complaint. The notice is small — one onboarding screen plus a line in `HELP_MESSAGE` — which is why it sits in Week 0 while the `/export` and `/delete` machinery waits.

## 6. Effort

Sizing: **S** under a day · **M** two to four days · **L** one to two weeks.

| Phase  | Item                                       | Size   | Note                                                                                                                                                                                                                                                                                                                                                                                                       |
| ------ | ------------------------------------------ | ------ | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Week 0 | P1 CI gate                                 | S      | ~15 lines of YAML                                                                                                                                                                                                                                                                                                                                                                                          |
| Week 0 | P2 Fly single-instance                     | S      | `fly scale count 1` + `[deploy] strategy = "immediate"`. Three lines; best risk/effort ratio in the plan                                                                                                                                                                                                                                                                                                   |
| Week 0 | P3 Crisis hotfix 3a                        | S      | Highest severity item in the document                                                                                                                                                                                                                                                                                                                                                                      |
| Week 0 | P4 Consent notice                          | S      |                                                                                                                                                                                                                                                                                                                                                                                                            |
| Week 0 | P5 Dead-code removal                       | S      | `journal.py:80` shadows the regex `_escape_md` at `:64`; `GUIDANCE_ERROR_MESSAGE` imported at `:28`, never used                                                                                                                                                                                                                                                                                            |
| —      | **Migration**                              | **L**  | 4–8 days. Blocking-I/O fix is M of that and is the most underestimated piece                                                                                                                                                                                                                                                                                                                               |
| Tier 0 | 1 Timezone-correct timestamps              | **M**  | Underestimated. The code is small; the test churn is not — date handling runs through `test_journal_service.py` and `test_entry_repo.py`, and `test_scheduler_service.py` patches `datetime` module-wide in ~22 places. `_update_streak` needs the user's timezone, which `JournalService` has no access to; add a `UserRepository` dependency rather than changing the call site, to keep it PTB-agnostic |
| Tier 0 | 7 Persistence                              | **M**  | Underestimated. An async `BasePersistence` is ~150 lines plus tests. The state-only variant halves it and sidesteps the PII problem                                                                                                                                                                                                                                                                        |
| Tier 0 | Indexes, timeouts, error handler, fallback | S each | Fold into adjacent PRs                                                                                                                                                                                                                                                                                                                                                                                     |
| Tier 0 | 2a Due-window + watermark                  | M      | Includes the double-fire trap                                                                                                                                                                                                                                                                                                                                                                              |
| Tier 0 | 2b LLM off the tick                        | M      | Needs a work queue or per-user `run_once`                                                                                                                                                                                                                                                                                                                                                                  |
| Tier 0 | 3b Content-triggered crisis                | M      | Lexicon, fail-closed guarantee, tests                                                                                                                                                                                                                                                                                                                                                                      |
| Tier 0 | 4 Instrumentation                          | M      | Code is S. The hard part is event taxonomy and defining retention — expect to rewrite the events once, so ship a deliberately over-broad set first                                                                                                                                                                                                                                                         |
| Tier 0 | Cohort tagging                             | S      | Two fields at onboarding: acquisition channel and a "currently in therapy" flag. **Must ship with item 4** — retroactive cohorting is impossible                                                                                                                                                                                                                                                           |
| Tier 1 | 5 Tag normalisation                        | M      | No backfill needed. Dependency of item 8                                                                                                                                                                                                                                                                                                                                                                   |
| Tier 1 | 6 `/export` v0 + `/delete`                 | M / S  | Crude Markdown export to test the core bet early                                                                                                                                                                                                                                                                                                                                                           |
| Tier 2 | 8 Export artifact                          | **L**  | The headline feature, four dependencies deep                                                                                                                                                                                                                                                                                                                                                               |
| Tier 2 | "Flag for session"                         | S–M    | Let users mark an entry to raise in session. Cheapest thing here that directly serves the artifact — ship it alongside the v0 export                                                                                                                                                                                                                                                                       |
| Tier 2 | 9 Onboarding rework                        | M      | Three blocking steps before any value is delivered                                                                                                                                                                                                                                                                                                                                                         |
| Tier 3 | 10 Retention mechanic                      | **L**  | Blocked on 4–6 weeks of item-4 data, not on engineering                                                                                                                                                                                                                                                                                                                                                    |

**Most likely underestimated, in order:** the blocking-I/O consequence of going async; persistence scope and its PII coupling; item 1's test churn.

## 7. Out of scope

- Clinician-facing accounts, dashboards, and audit surfaces — deferred until client-side usage justifies them.
- Data migration — test data only.
- Monetisation mechanics. The intended direction is in §9; nothing is built before Phase 7 data exists.
- Internationalisation. All 35 constants in `messages/strings.py` are module-level English with no i18n mechanism. Worth knowing; not scheduled.

## 8. Before building the export

One non-engineering prerequisite: talk to five therapists about what they would actually want to read in ninety seconds before a session. That conversation will shape the format more than any design decided here.

## 9. Monetisation direction

This is not scheduled. It is recorded so that choices made before it don't close it off.

- **First choice: therapists pay, clients use it free.** The export brief is what a therapist pays for. Start with a per-therapist invite code in `acquisition_source`, and charge outside Telegram.
- **Second choice: a paid tier inside the bot, paid in Telegram Stars.** Gate only the features that cost LLM calls. The crisis path, `/delete` and the basic export are never gated.
- **Organisation licences come later.** They need admin tooling, which §7 defers.

How to choose, from the Phase 4 events:

- **Therapist model:** how often users with `in_therapy = yes` export.
- **Paid tier:** how often users reach `DAILY_LLM_CALL_BUDGET`.

Trap: if exports are sent straight to a therapist, we become the therapist's data processor under GDPR, and a data processing agreement has to be in place before that feature ships.
