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
    RAI_VAULT_ACCOUNT_ID,
    ASSET_ID,
    CONTRACT_ADDRESS,
    RSTR_VAULT_ACCOUNT_ID,
    RSTR_CONTRACT_ADDRESS,
    RAI_REDEMPTION_VAULT_ACCOUNT_ID,
    RAI_REDEMPTION_ASSET_ID,
    RAI_REDEMPTION_CONTRACT_ADDRESS,
    RAIX_VAULT_ACCOUNT_ID,
    RAIX_CONTRACT_ADDRESS,
    RAIX_REDEMPTION_VAULT_ACCOUNT_ID,
    RAIX_REDEMPTION_ASSET_ID,
    RAIX_REDEMPTION_CONTRACT_ADDRESS,
    DUST_THRESHOLD_USDT,
    TESTNET_API_KEY,
    TESTNET_PRIVATE_KEY_PATH,
    TESTNET_VAULT_ACCOUNT_ID,
    TESTNET_ASSET_ID,
    TESTNET_NOTIFICATIONS_ENABLED,
    POLL_INTERVAL_SECONDS,
    STATE_FILE,
    NAV_VAULT_ID,
    RAI_NAV_CONTRACT,
    RSTR_NAV_CONTRACT,
    RAIX_NAV_CONTRACT,
)
from fireblocks_client import load_sdk, get_incoming_transactions, get_vault_balance, get_nav_submissions
from state import load_state, save_state

logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(message)s",
    level=logging.DEBUG,
)
logger = logging.getLogger(__name__)

RENOTIFY_SECONDS = 1800  # 30 minutes
SWEEP_RENOTIFY_SECONDS = 300  # 5-minute nag — sweep window is 16:00–16:25 SGT


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
    ts_ms = tx.get("createdAt") or tx.get("lastUpdated")
    if ts_ms:
        sgt = pytz.timezone("Asia/Singapore")
        dt = datetime.datetime.fromtimestamp(ts_ms / 1000, tz=pytz.utc).astimezone(sgt)
        date_str = dt.strftime("%d %b %Y %H:%M SGT")
    else:
        date_str = None

    lines.extend([
        label,
        f"Amount:  {amount} {asset}",
    ])
    if date_str:
        lines.append(f"Date:    {date_str}")
    lines.append(f"From:    {source_name}")
    if source_address:
        lines.append(f"Address: {source_address}")
    if tx_hash:
        lines.append(f'Tx hash: <a href="https://bscscan.com/tx/{tx_hash}">{tx_hash}</a>')
    lines.append(f"Fireblocks ID: {tx_id}")
    lines.append("@daryllty")
    return "\n".join(lines)


def format_amount_table(txs: list[dict]) -> str:
    lines = []
    total = 0.0
    asset = ""
    for tx in txs:
        amt = float(tx.get("amount") or 0)
        asset = html.escape(tx.get("assetId", ""))
        total += amt
        lines.append(f"  {amt:,.2f} {asset}")
    lines.append(f"  {'─' * 22}")
    lines.append(f"  <b>Total: {total:,.2f} {asset}</b>")
    return "\n".join(lines)


POLL_OPTIONS_DEFAULT = ["✅ Acknowledge"]
POLL_OPTIONS_SWEEP = ["✅ Transferred", "⏰ Delay"]


async def send_alert_with_poll(
    bot: Bot, alert_text: str, state: dict,
    renotify_seconds: int = RENOTIFY_SECONDS,
    options: list[str] = None,
) -> None:
    if options is None:
        options = POLL_OPTIONS_DEFAULT
    await bot.send_message(chat_id=CHAT_ID, text=alert_text, parse_mode="HTML")
    poll_msg = await bot.send_poll(
        chat_id=CHAT_ID,
        question="Tap to acknowledge this alert.",
        options=options,
        is_anonymous=False,
    )
    poll_id = poll_msg.poll.id
    state["pending_polls"][poll_id] = {
        "sent_at": int(time.time()),
        "alert_text": alert_text,
        "renotify_seconds": renotify_seconds,
        "options": options,
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


async def poll_mainnet_interval(bot: Bot, sdk, state: dict) -> None:
    now_ms = int(time.time() * 1000)
    after_ms = state["interval_last_checked_ms"]

    vault_checks = [
        (RAI_VAULT_ACCOUNT_ID,  ASSET_ID, CONTRACT_ADDRESS,  "SUBSCRIPTIONS"),
        (RSTR_VAULT_ACCOUNT_ID, ASSET_ID, RSTR_CONTRACT_ADDRESS, "SUBSCRIPTIONS"),
        (RAIX_VAULT_ACCOUNT_ID, ASSET_ID, RAIX_CONTRACT_ADDRESS, "SUBSCRIPTIONS"),
        (RAI_REDEMPTION_VAULT_ACCOUNT_ID, RAI_REDEMPTION_ASSET_ID, RAI_REDEMPTION_CONTRACT_ADDRESS, "REDEMPTIONS"),
    ]
    if RAIX_REDEMPTION_ASSET_ID:
        vault_checks.append(
            (RAIX_REDEMPTION_VAULT_ACCOUNT_ID, RAIX_REDEMPTION_ASSET_ID, RAIX_REDEMPTION_CONTRACT_ADDRESS, "REDEMPTIONS")
        )

    for vault_id, asset_id, contract_addr, category in vault_checks:
        min_amt = DUST_THRESHOLD_USDT if category == "SUBSCRIPTIONS" else 0.0
        txs = get_incoming_transactions(sdk, vault_id, asset_id, after_ms, contract_addr, min_amount=min_amt)
        for tx in txs:
            try:
                await send_alert_with_poll(bot, format_alert(tx, category=category), state)
            except TelegramError as e:
                logger.error(f"Interval poll alert error for {tx.get('id')}: {e}")

    state["interval_last_checked_ms"] = now_ms
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
        if 0 in option_ids:  # Acknowledge / Transferred
            del state["pending_polls"][poll_id]
            logger.info(f"Poll {poll_id} acknowledged")
            await bot.send_message(chat_id=CHAT_ID, text="✅ Acknowledged by @daryllty")
        elif 1 in option_ids:  # Delay — reset timer, re-nag after renotify_seconds
            state["pending_polls"][poll_id]["sent_at"] = int(time.time())
            logger.info(f"Poll {poll_id} delayed — resetting nag timer")

    # Re-alert for any poll unacknowledged or snoozed past its nag interval
    now = int(time.time())
    for poll_id, poll_data in list(state["pending_polls"].items()):
        if now - poll_data["sent_at"] >= poll_data.get("renotify_seconds", RENOTIFY_SECONDS):
            logger.info(f"Poll {poll_id} unacknowledged after 30min — re-sending alert")
            try:
                del state["pending_polls"][poll_id]
                await send_alert_with_poll(
                    bot, poll_data["alert_text"], state,
                    renotify_seconds=poll_data.get("renotify_seconds", RENOTIFY_SECONDS),
                    options=poll_data.get("options"),
                )
            except TelegramError as e:
                logger.error(f"Failed to re-send alert: {e}")

    save_state(STATE_FILE, state)


async def daily_mainnet_check(bot: Bot, sdk, state: dict) -> None:
    now_ms = int(time.time() * 1000)

    logger.info(f"Daily mainnet check — polling rAI subscription vault after {state['last_checked_ms']} ...")
    rai_sub_txs = get_incoming_transactions(sdk, RAI_VAULT_ACCOUNT_ID, ASSET_ID, state["last_checked_ms"], CONTRACT_ADDRESS, min_amount=DUST_THRESHOLD_USDT)

    logger.info(f"Daily mainnet check — polling rSTR subscription vault after {state['rstr_last_checked_ms']} ...")
    rstr_sub_txs = get_incoming_transactions(sdk, RSTR_VAULT_ACCOUNT_ID, ASSET_ID, state["rstr_last_checked_ms"], RSTR_CONTRACT_ADDRESS, min_amount=DUST_THRESHOLD_USDT)

    logger.info(f"Daily mainnet check — polling rAI redemption vault after {state['rai_redemption_last_checked_ms']} ...")
    rai_redemption_txs = get_incoming_transactions(
        sdk, RAI_REDEMPTION_VAULT_ACCOUNT_ID, RAI_REDEMPTION_ASSET_ID,
        state["rai_redemption_last_checked_ms"], RAI_REDEMPTION_CONTRACT_ADDRESS,
    )

    logger.info(f"Daily mainnet check — polling rAIX subscription vault after {state['raix_last_checked_ms']} ...")
    raix_sub_txs = get_incoming_transactions(
        sdk, RAIX_VAULT_ACCOUNT_ID, ASSET_ID,
        state["raix_last_checked_ms"], RAIX_CONTRACT_ADDRESS,
        min_amount=DUST_THRESHOLD_USDT,
    )

    raix_redemption_txs = []
    if RAIX_REDEMPTION_ASSET_ID:
        logger.info(f"Daily mainnet check — polling rAIX redemption vault after {state['raix_redemption_last_checked_ms']} ...")
        raix_redemption_txs = get_incoming_transactions(
            sdk, RAIX_REDEMPTION_VAULT_ACCOUNT_ID, RAIX_REDEMPTION_ASSET_ID,
            state["raix_redemption_last_checked_ms"], RAIX_REDEMPTION_CONTRACT_ADDRESS,
        )
    else:
        logger.info("Daily mainnet check — skipping rAIX redemption vault (RAIX_REDEMPTION_ASSET_ID not set)")

    subscription_txs = rai_sub_txs + rstr_sub_txs + raix_sub_txs
    redemption_txs = rai_redemption_txs + raix_redemption_txs
    if subscription_txs or redemption_txs:
        logger.info(
            f"Found {len(subscription_txs)} subscription(s) "
            f"(rAI={len(rai_sub_txs)}, rSTR={len(rstr_sub_txs)}), "
            f"{len(redemption_txs)} redemption(s) (rAI={len(rai_redemption_txs)})"
        )

    state["last_checked_ms"] = now_ms
    state["rstr_last_checked_ms"] = now_ms
    state["rai_redemption_last_checked_ms"] = now_ms
    state["raix_last_checked_ms"] = now_ms
    state["raix_redemption_last_checked_ms"] = now_ms
    save_state(STATE_FILE, state)

    total = len(subscription_txs) + len(redemption_txs)
    try:
        if total:
            parts = [
                f"✅ Daily vault check — {len(subscription_txs)} subscription(s), "
                f"{len(redemption_txs)} redemption(s)\n"
            ]
            if subscription_txs:
                sub_lines = []
                total_amt = 0.0
                asset = ""
                for vault_label, txs in [("rAI", rai_sub_txs), ("rSTR", rstr_sub_txs), ("rAIX", raix_sub_txs)]:
                    if txs:
                        vault_total = sum(float(tx.get("amount") or 0) for tx in txs)
                        asset = html.escape(txs[0].get("assetId", ""))
                        total_amt += vault_total
                        sub_lines.append(f"  {vault_label}: {vault_total:,.2f} {asset}")
                sub_lines.append(f"  {'─' * 22}")
                sub_lines.append(f"  <b>Total: {total_amt:,.2f} {asset}</b>")
                parts.append("<b>SUBSCRIPTIONS</b>\n" + "\n".join(sub_lines))
            if redemption_txs:
                parts.append(f"<b>REDEMPTIONS</b>\n{format_amount_table(redemption_txs)}")
            parts.append("@daryllty")
            await send_alert_with_poll(bot, "\n\n".join(parts), state)
        else:
            await bot.send_message(
                chat_id=CHAT_ID,
                text="✅ Polled the vault — no new incoming funds today.\n\nAll clear, relax for today!\n\n@daryllty",
            )
        logger.info(f"Daily summary sent (subs={len(subscription_txs)}, redemptions={len(redemption_txs)})")
    except TelegramError as e:
        logger.error(f"Failed to send daily summary: {e}")


async def send_sweep_reminder(bot: Bot, sdk, state: dict) -> None:
    rai_balance, rstr_balance, raix_balance = await asyncio.gather(
        asyncio.to_thread(get_vault_balance, sdk, RAI_VAULT_ACCOUNT_ID, ASSET_ID),
        asyncio.to_thread(get_vault_balance, sdk, RSTR_VAULT_ACCOUNT_ID, ASSET_ID),
        asyncio.to_thread(get_vault_balance, sdk, RAIX_VAULT_ACCOUNT_ID, ASSET_ID),
    )
    if rai_balance < 99 and rstr_balance < 99 and raix_balance < 99:
        logger.info(f"Sweep reminder skipped — rAI={rai_balance}, rSTR={rstr_balance}, rAIX={raix_balance}")
        return
    lines = ["@daryllty Sweep funds -> FOMO", ""]
    if rai_balance >= 99:
        lines.append(f"rAI Vault:  {rai_balance} {ASSET_ID}")
    if rstr_balance >= 99:
        lines.append(f"rSTR Vault: {rstr_balance} {ASSET_ID}")
    if raix_balance >= 99:
        lines.append(f"rAIX Vault: {raix_balance} {ASSET_ID}")
    try:
        await send_alert_with_poll(bot, "\n".join(lines), state, renotify_seconds=SWEEP_RENOTIFY_SECONDS, options=POLL_OPTIONS_SWEEP)
        logger.info(f"Sweep reminder sent (rAI={rai_balance}, rSTR={rstr_balance}, rAIX={raix_balance})")
    except TelegramError as e:
        logger.error(f"Failed to send sweep reminder: {e}")


NAV_CONTRACTS = {
    addr: name
    for addr, name in [
        (RAI_NAV_CONTRACT, "rAI"),
        (RSTR_NAV_CONTRACT, "rSTR"),
        (RAIX_NAV_CONTRACT, "rAIX"),
    ]
    if addr
}


async def send_nav_alert(bot: Bot, fund_name: str, tx: dict) -> None:
    sgt = pytz.timezone("Asia/Singapore")
    time_str = datetime.datetime.now(tz=sgt).strftime("%-I:%M%p SGT").lower()
    tx_hash = html.escape(tx.get("txHash", ""))
    fb_id = html.escape(str(tx.get("id", "")))
    lines = [
        f"✅ <b>NAV submitted — {html.escape(fund_name)}</b>",
        f"Confirmed on BSC at {time_str}.",
    ]
    if tx_hash:
        lines.append(f'Tx: <a href="https://bscscan.com/tx/{tx_hash}">{tx_hash}</a>')
    lines.append(f"Fireblocks ID: {fb_id}")
    lines.append("@daryllty")
    await bot.send_message(chat_id=CHAT_ID, text="\n".join(lines), parse_mode="HTML")


async def poll_nav_submissions(bot: Bot, sdk, nav_state: dict, scheduler) -> None:
    sgt = pytz.timezone("Asia/Singapore")
    now_sgt = datetime.datetime.now(tz=sgt)

    if now_sgt.hour >= 10:
        try:
            scheduler.remove_job("nav_poll")
        except Exception:
            pass
        logger.info("NAV watch window closed (10:00AM SGT)")
        return

    txs = get_nav_submissions(sdk, NAV_VAULT_ID, list(NAV_CONTRACTS.keys()), nav_state["since_ms"])
    for tx in txs:
        dest_addr = tx.get("destinationAddress", "")
        if not dest_addr:
            dest = tx.get("destination", {})
            if dest.get("type") == "ONE_TIME_ADDRESS":
                dest_addr = dest.get("oneTimeAddress", {}).get("address", "")
        if not dest_addr:
            dest_addr = (tx.get("extraParameters") or {}).get("contractAddress", "")
        fund = NAV_CONTRACTS.get(dest_addr.lower())
        if not fund or fund in nav_state["alerted"]:
            continue
        try:
            await send_nav_alert(bot, fund, tx)
            nav_state["alerted"].add(fund)
            logger.info(f"NAV alert sent for {fund}")
        except TelegramError as e:
            logger.error(f"Failed to send NAV alert for {fund}: {e}")

    if nav_state["alerted"] >= set(NAV_CONTRACTS.values()):
        try:
            scheduler.remove_job("nav_poll")
        except Exception:
            pass
        logger.info("All NAV submissions confirmed — watch stopped")


async def start_nav_watch(bot: Bot, sdk, nav_state: dict, scheduler) -> None:
    # Always scan from 9:00AM SGT so restarts during the window don't miss earlier txs
    sgt = pytz.timezone("Asia/Singapore")
    window_start = datetime.datetime.now(tz=sgt).replace(hour=9, minute=0, second=0, microsecond=0)
    nav_state["since_ms"] = int(window_start.timestamp() * 1000)
    nav_state["alerted"] = set()
    scheduler.add_job(
        poll_nav_submissions,
        "interval",
        seconds=30,
        kwargs={"bot": bot, "sdk": sdk, "nav_state": nav_state, "scheduler": scheduler},
        id="nav_poll",
        next_run_time=datetime.datetime.now(),
        replace_existing=True,
    )
    logger.info("NAV watch started (9AM SGT — polling every 30s until 9:30AM)")


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
        poll_mainnet_interval,
        "interval",
        seconds=300,
        kwargs={"bot": bot, "sdk": sdk, "state": state},
        id="mainnet_interval_poll",
        next_run_time=datetime.datetime.now() + datetime.timedelta(seconds=10),
    )
    scheduler.add_job(
        daily_mainnet_check,
        CronTrigger(day_of_week="mon-fri", hour=15, minute=30, timezone=sgt),
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
        CronTrigger(day_of_week="mon-fri", hour=16, minute=0, timezone=sgt),
        kwargs={"bot": bot, "sdk": sdk, "state": state},
        id="sweep_reminder",
    )

    nav_state = {"since_ms": 0, "alerted": set()}
    if NAV_VAULT_ID and NAV_CONTRACTS:
        scheduler.add_job(
            start_nav_watch,
            CronTrigger(day_of_week="tue-sat", hour=9, minute=0, timezone=sgt),
            kwargs={"bot": bot, "sdk": sdk, "nav_state": nav_state, "scheduler": scheduler},
            id="nav_watch_start",
            misfire_grace_time=1800,
        )
        logger.info(f"NAV watch registered for Tue-Sat 9:00AM SGT (vault {NAV_VAULT_ID}, {len(NAV_CONTRACTS)} contracts)")
    else:
        logger.warning("NAV watch disabled — set NAV_VAULT_ID + NAV contract addresses in env")

    scheduler.start()

    # If the bot starts (or restarts) during the NAV watch window, kick off the poller immediately.
    if NAV_VAULT_ID and NAV_CONTRACTS:
        now_sgt = datetime.datetime.now(tz=sgt)
        in_window = now_sgt.weekday() in (1, 2, 3, 4, 5) and now_sgt.hour == 9
        if in_window:
            logger.info("Started within NAV watch window — launching poller immediately")
            await start_nav_watch(bot=bot, sdk=sdk, nav_state=nav_state, scheduler=scheduler)
    testnet_status = "enabled" if TESTNET_NOTIFICATIONS_ENABLED else "disabled"
    logger.info(f"Running. Mainnet interval poll every 5min, daily check Mon-Fri 15:30 SGT, sweep reminder Mon-Fri 16:00 SGT, ack check every 5s. Testnet notifications: {testnet_status}.")

    try:
        await asyncio.Event().wait()
    except (KeyboardInterrupt, SystemExit):
        logger.info("Shutting down...")
        scheduler.shutdown()


if __name__ == "__main__":
    asyncio.run(main())
