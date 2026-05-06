import asyncio
from telegram import Bot
from config import BOT_TOKEN, CHAT_ID
from bot import format_alert, send_alert_with_poll
from state import load_state, save_state
from config import STATE_FILE

fake_tx = {
    "id": "test-tx-001",
    "assetId": "USDT_BSC",
    "amount": "200.00",
    "direction": "INCOMING",
    "txHash": "0xabc123def456abc123def456abc123def456abc123def456abc123def456abc1",
    "source": {"name": "External Wallet"},
    "sourceAddress": "0xde0b295669a9fd93d5f28d9ec85e40f4cb697bae",
    "destination": {"type": "VAULT_ACCOUNT", "id": "4"},
}

async def main():
    bot = Bot(token=BOT_TOKEN)
    state = load_state(STATE_FILE)
    alert_text = format_alert(fake_tx)
    await send_alert_with_poll(bot, alert_text, state)
    save_state(STATE_FILE, state)
    print("Alert + poll sent.")

asyncio.run(main())
