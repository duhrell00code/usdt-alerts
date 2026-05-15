import asyncio
from telegram import Bot
from config import BOT_TOKEN, CHAT_ID, STATE_FILE
from bot import format_alert, send_alert_with_poll
from state import load_state, save_state

fake_subscription_tx = {
    "id": "test-sub-001",
    "assetId": "USDT_BSC",
    "amount": "200.00",
    "direction": "INCOMING",
    "txHash": "0xabc123def456abc123def456abc123def456abc123def456abc123def456abc1",
    "source": {"name": "External Wallet"},
    "sourceAddress": "0xde0b295669a9fd93d5f28d9ec85e40f4cb697bae",
    "destination": {"type": "VAULT_ACCOUNT", "id": "4"},
}

fake_redemption_tx = {
    "id": "test-red-001",
    "assetId": "RAI_BSC_FW1X",
    "amount": "150.00",
    "direction": "INCOMING",
    "txHash": "0xdeadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeef",
    "source": {"name": "Investor Wallet"},
    "sourceAddress": "0xfeedfacefeedfacefeedfacefeedfacefeedface",
    "destination": {"type": "VAULT_ACCOUNT", "id": "5"},
}

async def main():
    bot = Bot(token=BOT_TOKEN)
    state = load_state(STATE_FILE)
    await send_alert_with_poll(bot, format_alert(fake_subscription_tx, category="SUBSCRIPTIONS"), state)
    await send_alert_with_poll(bot, format_alert(fake_redemption_tx, category="REDEMPTIONS"), state)
    save_state(STATE_FILE, state)
    print("Alert + poll sent for SUBSCRIPTIONS and REDEMPTIONS.")

asyncio.run(main())
