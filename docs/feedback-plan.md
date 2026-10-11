# In-bot feedback (`/feedback`)

## Context
Users have no way to send ideas, suggestions or complaints. This adds a one-shot flow: the user sends one message, it is stored, and the admins get a notification.

## UX
- `/feedback`, plus a "Send feedback" button in the Settings menu. Keep it off the main menu, and per the Plus rule keep it out of the entry flow too.
- The bot replies: "What would you like to tell us? One message, any length up to 2000 chars. /cancel to skip."
- The user's next text is saved and acknowledged ("Thanks, it reaches a real person."). The conversation returns to `MAIN_MENU`.

## Implementation
- **State:** append `FEEDBACK_TEXT = 12` to `bot/handlers/journal/states.py` (append only), and pin it in `tests/test_states.py`.
- **Handler:** new `bot/handlers/journal/feedback.py` containing `request_feedback` and `handle_feedback_text`. Decorate both with `@service_errors` and route service calls through `asyncio.to_thread`. Wire them in `journal/__init__.py`: `CommandHandler('feedback', ...)` goes in `commands`, so it is both an entry point and a fallback, and `FEEDBACK_TEXT` gets a text handler in `states`. Add the Settings button in `settings.py`.
- **Safety:** run `services.safety.detect_crisis` on the text. On a match, send the crisis resources first, exactly as `checkin.py` does. People write distress anywhere.
- **Storage:** new `feedback_collection()` in `db/db.py`, plus `FeedbackRepository` and `FeedbackService.submit(telegram_id, text)`. Each document holds `{telegram_id, text, created_at (UTC), is_plus}`. Add a `telegram_id` index in `db/indexes.py`.
- **Admin notify:** forward the text to each id in `ADMIN_TELEGRAM_IDS` as `Feedback from <telegram_id>: …`, in plain text rather than Markdown. A failed forward is logged and never shown to the user, because the DB row is the record.
- **Abuse cap:** at most 5 submissions per user per local day. Count the rows in the repo; no LLM is involved.
- **Analytics:** a `feedback_sent` event with `text_length` and `source=prompt|command|settings`. Never the text.
- **Strings:** all copy goes in `messages/strings.py`. Add `/feedback` to `HELP_MESSAGE`.

## Privacy (required)
- Add `feedback` to the `AccountService` `/delete` fan-out. `tests/test_account_service.py` fails until it is added.
- `PRIVACY_NOTICE` and the `/delete` text must say that feedback is stored, and that copies already sent to the team in Telegram can't be recalled.
- Update CONTEXT.md, in the scope list and in State and Data Rules: feedback is user-written text stored outside `entries`.
- Update the CLAUDE.md tables: the repo and service lists, and the PII surfaces.

## One-time feedback ask after N check-ins
- **Where:** `handle_entry_text` in `bot/handlers/journal/checkin.py`, right after the completion message is sent and before the guidance-offer branch.
- **Due when all of these hold:**
  - the entry is the daily check-in (`first_of_day`), never a note
  - no crisis trigger fired
  - the mood is above `LOW_MOOD_THRESHOLD`, so a struggling user never gets a guidance offer and an ask together
  - `stats['total_entries'] >= FEEDBACK_ASK_AFTER`, which is 7 and sits in `states.py` next to the mood thresholds (`stats` is already loaded at that point)
  - the user has no `feedback_prompted_at`
- **What:** one separate short message, `FEEDBACK_ASK` in strings. For example: "You've checked in 7 times — thank you. Is there anything that would make this more useful? Tap /feedback, or just ignore this." No keyboard change: the conversation stays on `MAIN_MENU`.
- **Once:** set `feedback_prompted_at` (UTC) through the non-upserting `UserService.update` *before* sending, so a failed send never repeats the ask. Wrap the step in its own try/except, so a failure there never costs the user their check-in reply.
- **Analytics:** a `feedback_prompted` event with no props, so the ask's conversion can be measured against `feedback_sent` with `source=prompt`.
- **Plus rule untouched:** this is not a Plus offer. `tests/test_plus.py` still passes, because the ask copy never mentions Plus.

## Later (not now)
- `/reply <telegram_id> <text>` for admins to answer feedback.

## Verification
- Tests for the command:
  - routing: feedback text reaches `handle_feedback_text`, not `recover_state`
  - the state pin
  - the delete fan-out
  - a crisis-lexicon match sends resources
  - the daily cap
  - an admin-send failure still saves the feedback
- Tests for the ask:
  - it shows on the 7th daily check-in
  - it never shows on a note, on low mood or crisis, or on a second qualifying check-in
  - a failed `update` still delivers the check-in reply
- Run `.venv/bin/pytest`, `flake8` and `black .`. Do not run `main.py` locally, because `.env` holds the live token. Check by hand on a test bot or after deploy.
- Add `feedback` to the BotFather `/setcommands` list.
