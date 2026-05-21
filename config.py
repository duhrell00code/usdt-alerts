import os
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")

# Mainnet
FIREBLOCKS_API_KEY = os.getenv("FIREBLOCKS_API_KEY")
FIREBLOCKS_PRIVATE_KEY_PATH = os.getenv("FIREBLOCKS_PRIVATE_KEY_PATH")
RAI_VAULT_ACCOUNT_ID = os.getenv("RAI_VAULT_ACCOUNT_ID")
ASSET_ID = os.getenv("ASSET_ID")
CONTRACT_ADDRESS = os.getenv("CONTRACT_ADDRESS", "").lower() or None

# rSTR Vault (mainnet)
RSTR_VAULT_ACCOUNT_ID = os.getenv("RSTR_VAULT_ACCOUNT_ID")
RSTR_CONTRACT_ADDRESS = os.getenv("RSTR_CONTRACT_ADDRESS", "").lower() or None

# rAI Redemption Vault (mainnet) — receives rAI tokens from investors redeeming
RAI_REDEMPTION_VAULT_ACCOUNT_ID = os.getenv("RAI_REDEMPTION_VAULT_ACCOUNT_ID")
RAI_REDEMPTION_ASSET_ID = os.getenv("RAI_REDEMPTION_ASSET_ID")
RAI_REDEMPTION_CONTRACT_ADDRESS = os.getenv("RAI_REDEMPTION_CONTRACT_ADDRESS", "").lower() or None

# Dust filter — subscription vaults only (not redemption, which uses rAI tokens)
DUST_THRESHOLD_USDT = float(os.getenv("DUST_THRESHOLD_USDT", "1.0"))

# Testnet
TESTNET_API_KEY = os.getenv("TESTNET_API_KEY")
TESTNET_PRIVATE_KEY_PATH = os.getenv("TESTNET_PRIVATE_KEY_PATH")
TESTNET_VAULT_ACCOUNT_ID = os.getenv("TESTNET_VAULT_ACCOUNT_ID")
TESTNET_ASSET_ID = os.getenv("TESTNET_ASSET_ID")

TESTNET_NOTIFICATIONS_ENABLED = os.getenv("TESTNET_NOTIFICATIONS_ENABLED", "true").lower() == "true"

POLL_INTERVAL_SECONDS = int(os.getenv("POLL_INTERVAL_SECONDS", "60"))
STATE_FILE = os.getenv("STATE_FILE", "state.json")

for name, val in [
    ("BOT_TOKEN", BOT_TOKEN),
    ("CHAT_ID", CHAT_ID),
    ("FIREBLOCKS_API_KEY", FIREBLOCKS_API_KEY),
    ("RAI_VAULT_ACCOUNT_ID", RAI_VAULT_ACCOUNT_ID),
    ("ASSET_ID", ASSET_ID),
    ("RSTR_VAULT_ACCOUNT_ID", RSTR_VAULT_ACCOUNT_ID),
    ("RAI_REDEMPTION_VAULT_ACCOUNT_ID", RAI_REDEMPTION_VAULT_ACCOUNT_ID),
    ("RAI_REDEMPTION_ASSET_ID", RAI_REDEMPTION_ASSET_ID),
    ("TESTNET_API_KEY", TESTNET_API_KEY),
    ("TESTNET_VAULT_ACCOUNT_ID", TESTNET_VAULT_ACCOUNT_ID),
    ("TESTNET_ASSET_ID", TESTNET_ASSET_ID),
]:
    if not val:
        raise ValueError(f"{name} is not set in .env")

# At least one of key file or key content must be available
if not FIREBLOCKS_PRIVATE_KEY_PATH and not os.getenv("FIREBLOCKS_PRIVATE_KEY"):
    raise ValueError("Either FIREBLOCKS_PRIVATE_KEY_PATH or FIREBLOCKS_PRIVATE_KEY must be set")
