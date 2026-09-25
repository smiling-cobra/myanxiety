# AnxietyJournal Bot

A private Telegram chatbot for daily mood check-ins and anxiety journalling. Replies empathetically via Claude, tracks streaks, and surfaces patterns over time.

## Requirements

- Python 3.11+
- MongoDB
- Telegram bot token
- Anthropic API key

## Setup

Copy `.env.example` to `.env` and fill in the values:

```
TELEGRAM_TOKEN=
CLAUDE_API_KEY=
MONGODB_URI=
ANTHROPIC_MODEL=claude-3-5-sonnet-latest
```

`ANTHROPIC_MODEL` is optional. If not set, the app falls back to `claude-3-5-sonnet-latest`.

Two more optional variables support Plus, the paid tier:

- `ADMIN_TELEGRAM_IDS`: comma-separated Telegram ids allowed `/admin_plus` (switch your own Plus on or off, for testing) and `/refund <charge_id>`. Unset means nobody.
- `SUPPORT_CONTACT`: the @username or email that `/paysupport` gives for payment problems.

For Fly.io deployments, set or update the model with:

```bash
fly secrets set ANTHROPIC_MODEL=<your-enabled-model-id>
```

## Deployment

Pushing to `master` runs lint and tests, and deploys to Fly only if they pass
(`.github/workflows/fly-deploy.yml`). There is no manual step in the normal path.

The bot polls Telegram with `getUpdates`, which permits exactly one consumer per
token. Two running machines means two pollers, 409 Conflict responses, and
duplicate reminders — so the app must stay at a single instance:

```bash
fly scale count 1
```

That is a one-time, per-app setting and cannot live in `fly.toml`. The matching
half — `[deploy] strategy = 'immediate'`, which stops the old machine before
starting the new one instead of overlapping them — is in `fly.toml`.

## Run

```bash
# Directly
python3 main.py

# Via Docker
docker-compose up
```

## Test

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
.venv/bin/pytest
```

`requirements.txt` holds runtime dependencies only — the production image does not
install linters or a test runner. `requirements-dev.txt` includes it and adds those.

## Docker

```bash
# Build image
docker build -t anxiety-journal-bot .

# List running containers
docker ps

# Open shell in container
docker exec -it <container_id> /bin/bash
```
