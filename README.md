# Steuer Chatbot

A personal Telegram bot that captures Entries for German income-tax deductions
(see `CONTEXT.md` for the domain vocabulary).

## Running

```sh
cp example.env .env   # then fill in TELEGRAM_BOT_TOKEN and ALLOWED_TELEGRAM_USER_ID
docker compose up -d
```

The `entries` table is created automatically when the bot starts. Receipt files are
stored on the host under `RECEIPTS_DIR` (default `./data/receipts`), as
`{category}/{entry_id}{extension}`.

In Telegram, send `/start` to log an Entry and `/cancel` to abort the current flow.
Set your round-trip Commute Distance once with `/setdistance <km>` (e.g. `/setdistance 42`);
sending it again overwrites the stored value.
Delete a wrongly logged Entry (and its Receipt file) with `/delete <id>`, using the
number the bot replied with when saving it.

## Tests

Tests need [uv](https://docs.astral.sh/uv/) and a running Docker daemon: the
service-layer tests start a throwaway Postgres container via testcontainers.

```sh
uv run pytest        # test suite
uv run mypy src tests  # typecheck
```
