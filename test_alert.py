import asyncio
from telegram import Bot
from config import BOT_TOKEN, CHAT_ID, ASSET_ID
from bot import format_alert, send_alert_with_poll, SWEEP_RENOTIFY_SECONDS

fake_sub_tx_1 = {
    "id": "test-sub-001",
    "assetId": "USDT_BSC",
    "amount": "5000.00",
    "txHash": "0xabc123def456abc123def456abc123def456abc123def456abc123def456abc1",
    "source": {"name": "External"},
    "sourceAddress": "0xde0b295669a9fd93d5f28d9ec85e40f4cb697bae",
    "destination": {"type": "VAULT_ACCOUNT", "id": "4"},
}

fake_sub_tx_2 = {
    "id": "test-sub-002",
    "assetId": "USDT_BSC",
    "amount": "2500.00",
    "txHash": "0xbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
    "source": {"name": "External"},
    "sourceAddress": "0xfeedfacefeedfacefeedfacefeedfacefeedface",
    "destination": {"type": "VAULT_ACCOUNT", "id": "4"},
}

fake_redemption_tx = {
    "id": "test-red-001",
    "assetId": "RAI_BSC_FW1X",
    "amount": "150.00",
    "txHash": "0xdeadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeef",
    "source": {"name": "Investor Wallet"},
    "sourceAddress": "0x1234567890abcdef1234567890abcdef12345678",
    "destination": {"type": "VAULT_ACCOUNT", "id": "5"},
}


async def main():
    bot = Bot(token=BOT_TOKEN)
    # Temporary in-memory state — does not touch state.json
    state = {"pending_polls": {}}

    print("--- TEST 1: daily check with 2 subs + 1 redemption ---")
    subscription_txs = [fake_sub_tx_1, fake_sub_tx_2]
    redemption_txs = [fake_redemption_tx]

    for tx in subscription_txs:
        await bot.send_message(chat_id=CHAT_ID, text=format_alert(tx, category="SUBSCRIPTIONS"), parse_mode="HTML")
    for tx in redemption_txs:
        await bot.send_message(chat_id=CHAT_ID, text=format_alert(tx, category="REDEMPTIONS"), parse_mode="HTML")

    total = len(subscription_txs) + len(redemption_txs)
    summary = (
        f"✅ Daily vault check — {len(subscription_txs)} subscription(s), "
        f"{len(redemption_txs)} redemption(s), alerts sent above.\n\n@daryllty"
    )
    await send_alert_with_poll(bot, summary, state)
    print(f"Daily check sent. pending_polls now has {len(state['pending_polls'])} entry.")

    print("--- TEST 2: sweep reminder (5-min nag poll) ---")
    sweep_text = f"@daryllty Sweep funds -> FOMO\n\nrAI Vault:  205.00 {ASSET_ID}"
    await send_alert_with_poll(bot, sweep_text, state, renotify_seconds=SWEEP_RENOTIFY_SECONDS)
    print(f"Sweep reminder sent. pending_polls now has {len(state['pending_polls'])} entries.")

    print("Done. Acknowledge or snooze the polls in Telegram.")


asyncio.run(main())
