import asyncio
import datetime
import html
import logging
import time
from typing import Optional
import pytz

from telegram import Bot
from telegram.error import TelegramError
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from config import (
    BOT_TOKEN,
    CHAT_ID,
    FIREBLOCKS_API_KEY,
    FIREBLOCKS_PRIVATE_KEY_PATH,
    VAULT_ACCOUNT_ID,
    ASSET_ID,
    CONTRACT_ADDRESS,
    RSTR_VAULT_ACCOUNT_ID,
    RSTR_CONTRACT_ADDRESS,
    RAI_REDEMPTION_VAULT_ACCOUNT_ID,
    RAI_REDEMPTION_ASSET_ID,
    RAI_REDEMPTION_CONTRACT_ADDRESS,
    TESTNET_API_KEY,
    TESTNET_PRIVATE_KEY_PATH,
    TESTNET_VAULT_ACCOUNT_ID,
    TESTNET_ASSET_ID,
    TESTNET_NOTIFICATIONS_ENABLED,
    POLL_INTERVAL_SECONDS,
    STATE_FILE,
)
from fireblocks_client import load_sdk, get_incoming_transactions, get_vault_balance
from state import load_state, save_state

logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(message)s",
    level=logging.DEBUG,
)
logger = logging.getLogger(__name__)

RENOTIFY_SECONDS = 1800  # 30 minutes


def format_alert(tx: dict, category: Optional[str] = None, testnet: bool = False) -> str:
    amount = html.escape(str(tx.get("amount", "?")))
    asset = html.escape(tx.get("assetId", ""))
    tx_hash = html.escape(tx.get("txHash", ""))
    tx_id = html.escape(str(tx.get("id", "")))
    source_name = html.escape((tx.get("source") or {}).get("name", "unknown"))
    source_address = html.escape(tx.get("sourceAddress", ""))

    label = "💰 Incoming transfer received!" if not testnet else "🧪 [TESTNET] Incoming transfer received!"
    lines = []
    if category:
        lines.append(f"<b>{html.escape(category)}</b>")
    lines.extend([
        label,
        f"Amount:  {amount} {asset}",
        f"From:    {source_name}",
    ])
    if source_address:
        lines.append(f"Address: {source_address}")
    if tx_hash:
        lines.append(f"Tx hash: {tx_hash}")
    lines.append(f"Fireblocks ID: {tx_id}")
    lines.append("@daryllty")
    return "\n".join(lines)


async def send_alert_with_poll(bot: Bot, alert_text: str, state: dict) -> None:
    await bot.send_message(chat_id=CHAT_ID, text=alert_text, parse_mode="HTML")
    poll_msg = await bot.send_poll(
        chat_id=CHAT_ID,
        question="Respond to this transfer alert.",
        options=["✅ Acknowledge", "⏰ Snooze (30 min)"],
        is_anonymous=False,
    )
    poll_id = poll_msg.poll.id
    state["pending_polls"][poll_id] = {
        "sent_at": int(time.time()),
        "alert_text": alert_text,
    }
    logger.info(f"Poll sent: {poll_id}")


async def poll_fireblocks(
    bot: Bot,
    sdk,
    state: dict,
    vault_account_id: str,
    asset_id: str,
    contract_address: str,
    state_key: str,
    category: Optional[str] = None,
    testnet: bool = False,
) -> None:
    now_ms = int(time.time() * 1000)
    after_ms = state[state_key]
    label = "testnet" if testnet else "mainnet"

    logger.info(f"Polling Fireblocks ({label}) for transactions after {after_ms} ...")
    txs = get_incoming_transactions(sdk, vault_account_id, asset_id, after_ms, contract_address)

    if txs:
        logger.info(f"Found {len(txs)} new {label} transaction(s)")
    for tx in txs:
        try:
            alert_text = format_alert(tx, category=category, testnet=testnet)
            await send_alert_with_poll(bot, alert_text, state)
        except TelegramError as e:
            logger.error(f"Failed to send alert for tx {tx.get('id')}: {e}")

    state[state_key] = now_ms
    save_state(STATE_FILE, state)


async def check_unacknowledged_polls(bot: Bot, state: dict) -> None:
    try:
        updates = await bot.get_updates(
            offset=state["update_offset"],
            allowed_updates=["poll_answer"],
        )
    except TelegramError as e:
        logger.error(f"Failed to fetch updates: {e}")
        return

    for update in updates:
        state["update_offset"] = update.update_id + 1
        if not update.poll_answer:
            continue
        poll_id = update.poll_answer.poll_id
        option_ids = update.poll_answer.option_ids
        if poll_id not in state["pending_polls"]:
            continue
        if 0 in option_ids:  # Acknowledge
            del state["pending_polls"][poll_id]
            logger.info(f"Poll {poll_id} acknowledged")
            await bot.send_message(chat_id=CHAT_ID, text="✅ Transfer acknowledged by @daryllty")
        elif 1 in option_ids:  # Snooze
            state["pending_polls"][poll_id]["sent_at"] = int(time.time())
            logger.info(f"Poll {poll_id} snoozed — resetting 30-min timer")
            await bot.send_message(chat_id=CHAT_ID, text="⏰ Snoozed — will remind again in 30 minutes.")

    # Re-alert for any poll unacknowledged or snoozed past 30 minutes
    now = int(time.time())
    for poll_id, poll_data in list(state["pending_polls"].items()):
        if now - poll_data["sent_at"] >= RENOTIFY_SECONDS:
            logger.info(f"Poll {poll_id} unacknowledged after 30min — re-sending alert")
            try:
                del state["pending_polls"][poll_id]
                await send_alert_with_poll(bot, poll_data["alert_text"], state)
            except TelegramError as e:
                logger.error(f"Failed to re-send alert: {e}")

    save_state(STATE_FILE, state)


async def daily_mainnet_check(bot: Bot, sdk, state: dict) -> None:
    now_ms = int(time.time() * 1000)

    logger.info(f"Daily mainnet check — polling rAI subscription vault after {state['last_checked_ms']} ...")
    rai_sub_txs = get_incoming_transactions(sdk, VAULT_ACCOUNT_ID, ASSET_ID, state["last_checked_ms"], CONTRACT_ADDRESS)

    logger.info(f"Daily mainnet check — polling rSTR subscription vault after {state['rstr_last_checked_ms']} ...")
    rstr_sub_txs = get_incoming_transactions(sdk, RSTR_VAULT_ACCOUNT_ID, ASSET_ID, state["rstr_last_checked_ms"], RSTR_CONTRACT_ADDRESS)

    logger.info(f"Daily mainnet check — polling rAI redemption vault after {state['rai_redemption_last_checked_ms']} ...")
    rai_redemption_txs = get_incoming_transactions(
        sdk, RAI_REDEMPTION_VAULT_ACCOUNT_ID, RAI_REDEMPTION_ASSET_ID,
        state["rai_redemption_last_checked_ms"], RAI_REDEMPTION_CONTRACT_ADDRESS,
    )

    subscription_txs = rai_sub_txs + rstr_sub_txs
    redemption_txs = rai_redemption_txs
    if subscription_txs or redemption_txs:
        logger.info(
            f"Found {len(subscription_txs)} subscription(s) "
            f"(rAI={len(rai_sub_txs)}, rSTR={len(rstr_sub_txs)}), "
            f"{len(redemption_txs)} redemption(s) (rAI={len(rai_redemption_txs)})"
        )

    for tx in subscription_txs:
        try:
            alert_text = format_alert(tx, category="SUBSCRIPTIONS", testnet=False)
            await send_alert_with_poll(bot, alert_text, state)
        except TelegramError as e:
            logger.error(f"Failed to send subscription alert for tx {tx.get('id')}: {e}")

    for tx in redemption_txs:
        try:
            alert_text = format_alert(tx, category="REDEMPTIONS", testnet=False)
            await send_alert_with_poll(bot, alert_text, state)
        except TelegramError as e:
            logger.error(f"Failed to send redemption alert for tx {tx.get('id')}: {e}")

    state["last_checked_ms"] = now_ms
    state["rstr_last_checked_ms"] = now_ms
    state["rai_redemption_last_checked_ms"] = now_ms
    save_state(STATE_FILE, state)

    total = len(subscription_txs) + len(redemption_txs)
    if total:
        summary = (
            f"✅ Daily vault check — {len(subscription_txs)} subscription(s), "
            f"{len(redemption_txs)} redemption(s), alerts sent above.\n\n@daryllty"
        )
    else:
        summary = "✅ Polled the vault — no new incoming funds today.\n\nAll clear, relax for today!\n\n@daryllty"

    try:
        await bot.send_message(chat_id=CHAT_ID, text=summary)
        logger.info(f"Daily summary sent (subs={len(subscription_txs)}, redemptions={len(redemption_txs)})")
    except TelegramError as e:
        logger.error(f"Failed to send daily summary: {e}")


async def send_sweep_reminder(bot: Bot, sdk) -> None:
    rai_balance, rstr_balance = await asyncio.gather(
        asyncio.to_thread(get_vault_balance, sdk, VAULT_ACCOUNT_ID, ASSET_ID),
        asyncio.to_thread(get_vault_balance, sdk, RSTR_VAULT_ACCOUNT_ID, ASSET_ID),
    )
    if rai_balance < 99 and rstr_balance < 99:
        logger.info(f"Sweep reminder skipped — rAI={rai_balance}, rSTR={rstr_balance}")
        return
    lines = ["@daryllty Sweep funds -> FOMO", ""]
    if rai_balance >= 99:
        lines.append(f"rAI Vault:  {rai_balance} {ASSET_ID}")
    if rstr_balance >= 99:
        lines.append(f"rSTR Vault: {rstr_balance} {ASSET_ID}")
    try:
        await bot.send_message(chat_id=CHAT_ID, text="\n".join(lines))
        logger.info(f"Sweep reminder sent (rAI={rai_balance}, rSTR={rstr_balance})")
    except TelegramError as e:
        logger.error(f"Failed to send sweep reminder: {e}")


async def main():
    bot = Bot(token=BOT_TOKEN)
    me = await bot.get_me()
    logger.info(f"Bot started: @{me.username}")

    sdk = load_sdk(FIREBLOCKS_API_KEY, FIREBLOCKS_PRIVATE_KEY_PATH)
    logger.info("Fireblocks mainnet SDK initialised")

    testnet_sdk = load_sdk(TESTNET_API_KEY, TESTNET_PRIVATE_KEY_PATH, env_var="TESTNET_FIREBLOCKS_PRIVATE_KEY")
    logger.info("Fireblocks testnet SDK initialised")

    state = load_state(STATE_FILE)
    logger.info(f"Resuming from last_checked_ms={state['last_checked_ms']}, pending polls={len(state['pending_polls'])}")

    scheduler = AsyncIOScheduler(job_defaults={"misfire_grace_time": 60})

    sgt = pytz.timezone("Asia/Singapore")
    scheduler.add_job(
        daily_mainnet_check,
        CronTrigger(day_of_week="tue-sat", hour=15, minute=30, timezone=sgt),
        kwargs={"bot": bot, "sdk": sdk, "state": state},
        id="fireblocks_poll_mainnet",
    )
    if TESTNET_NOTIFICATIONS_ENABLED:
        scheduler.add_job(
            poll_fireblocks,
            "interval",
            seconds=POLL_INTERVAL_SECONDS,
            kwargs={
                "bot": bot, "sdk": testnet_sdk, "state": state,
                "vault_account_id": TESTNET_VAULT_ACCOUNT_ID, "asset_id": TESTNET_ASSET_ID,
                "contract_address": None, "state_key": "testnet_last_checked_ms",
                "category": "SUBSCRIPTIONS", "testnet": True,
            },
            id="fireblocks_poll_testnet",
            next_run_time=datetime.datetime.now() + datetime.timedelta(seconds=5),
        )
    else:
        logger.info("Testnet notifications disabled — skipping testnet poll job")
    scheduler.add_job(
        check_unacknowledged_polls,
        "interval",
        seconds=5,
        kwargs={"bot": bot, "state": state},
        id="poll_check",
        next_run_time=datetime.datetime.now(),
    )

    scheduler.add_job(
        send_sweep_reminder,
        CronTrigger(day_of_week="tue-sat", hour=15, minute=30, timezone=sgt),
        kwargs={"bot": bot, "sdk": sdk},  # mainnet only
        id="sweep_reminder",
    )

    scheduler.start()
    testnet_status = "enabled" if TESTNET_NOTIFICATIONS_ENABLED else "disabled"
    logger.info(f"Running. Mainnet check Tue-Sat 15:30 SGT, ack check every 5s, sweep reminder Tue-Sat 15:30 SGT. Testnet notifications: {testnet_status}.")

    try:
        await asyncio.Event().wait()
    except (KeyboardInterrupt, SystemExit):
        logger.info("Shutting down...")
        scheduler.shutdown()


if __name__ == "__main__":
    asyncio.run(main())
