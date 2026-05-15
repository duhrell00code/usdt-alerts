# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A long-running Python worker that watches Fireblocks vaults for incoming transfers and pushes Telegram alerts. It runs on Railway (Procfile `worker: python bot.py`, Python 3.11). The deployed project is `zoological-inspiration` on Railway, not `extraordinary-flexibility`.

## Running

```bash
# local dev (needs .env populated from .env.example, plus the testnet/rSTR vars below)
source venv/bin/activate
python bot.py

# one-shot scripts (each reads config from .env and runs to completion)
python test_connection.py   # verify mainnet Fireblocks SDK auth + list last-24h txs
python test_testnet.py      # dump raw testnet txs with destination/asset matching
python test_alert.py        # send a fake alert + poll to Telegram to validate the chat
```

There is no test suite, linter, or build step. `requirements.txt` is the dependency manifest; install with `pip install -r requirements.txt`.

## Environment variables beyond `.env.example`

`.env.example` is incomplete. `config.py` also requires:

- `RSTR_VAULT_ACCOUNT_ID`, `RSTR_CONTRACT_ADDRESS` — second mainnet vault (rSTR), polled alongside the rAI vault on the daily check.
- `TESTNET_API_KEY`, `TESTNET_PRIVATE_KEY_PATH`, `TESTNET_VAULT_ACCOUNT_ID`, `TESTNET_ASSET_ID` — separate Fireblocks workspace for the testnet poller.
- `TESTNET_NOTIFICATIONS_ENABLED` (default `true`) — set to `false` to skip the testnet job entirely.
- `FIREBLOCKS_PRIVATE_KEY` / `TESTNET_FIREBLOCKS_PRIVATE_KEY` — used on Railway in place of the file path. `load_sdk` in `fireblocks_client.py` reads the env var first, falls back to the file, and replaces literal `\n` with newlines (Railway strips real newlines from env values).

## Architecture

Single-process asyncio app with one `AsyncIOScheduler` running four jobs:

1. **`daily_mainnet_check`** — cron at 15:30 SGT. Polls both mainnet vaults (rAI via `VAULT_ACCOUNT_ID`/`CONTRACT_ADDRESS`, rSTR via `RSTR_VAULT_ACCOUNT_ID`/`RSTR_CONTRACT_ADDRESS`), sends per-tx alert+poll, then **always** sends a daily summary message (this is intentional — see commit `961f1ef`).
2. **`poll_fireblocks` (testnet)** — interval `POLL_INTERVAL_SECONDS` (default 60). Only registered when `TESTNET_NOTIFICATIONS_ENABLED`.
3. **`check_unacknowledged_polls`** — every 5 seconds. Reads `bot.get_updates(allowed_updates=["poll_answer"])`, advances `state["update_offset"]`, handles `Acknowledge` (clears) and `Snooze` (resets timer). Re-sends any poll that has been pending ≥ `RENOTIFY_SECONDS` (30 min).
4. **`send_sweep_reminder`** — cron Mon–Fri 15:30 SGT. Fetches both mainnet vault balances in parallel via `asyncio.to_thread`; sends one consolidated message only if at least one vault is ≥ 99 of `ASSET_ID`.

State is a single JSON file (`STATE_FILE`, default `state.json`) persisted after every poll cycle. Keys: `last_checked_ms` (rAI), `rstr_last_checked_ms`, `testnet_last_checked_ms`, `update_offset` (Telegram long-poll cursor), `pending_polls` (poll_id → `{sent_at, alert_text}`). On fresh start, `load_state` seeds each cursor to `now − 10 min` so a restart still catches recent activity.

### Fireblocks tx filtering

`get_incoming_transactions` in `fireblocks_client.py` calls `sdk.get_transactions(after=…, status=COMPLETED, limit=50)` and then filters in Python by: matching `assetId`, `destination.type == "VAULT_ACCOUNT"`, `destination.id == vault_account_id`, and optionally `extraParameters.contractAddress` (lowercased). Fireblocks does not filter by destination server-side, hence the client-side pass.

### Alert + poll flow

`send_alert_with_poll` sends two Telegram messages: a plain-text alert, then a non-anonymous poll with `Acknowledge` / `Snooze` options. The poll ID is stored in `state["pending_polls"]`. Snooze resets `sent_at`; the 30-min re-alert path **deletes the old poll entry then re-sends a fresh alert+poll** (it does not edit the existing poll).

State mutations happen inside scheduler jobs and are all single-threaded under asyncio — no locking. Each job calls `save_state` before returning.

## Deployment notes

- Railway: set `FIREBLOCKS_PRIVATE_KEY` / `TESTNET_FIREBLOCKS_PRIVATE_KEY` with `\n`-escaped newlines (commit `4a12956`).
- `state.json` is local-only (in `.gitignore`); on Railway the worker starts with empty state and seeds the cursor 10 min back.
- Scheduler timezone is `Asia/Singapore` via `pytz`; do not assume UTC.
