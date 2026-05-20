import time
from config import FIREBLOCKS_API_KEY, FIREBLOCKS_PRIVATE_KEY_PATH, RAI_VAULT_ACCOUNT_ID, ASSET_ID
from fireblocks_client import load_sdk, get_incoming_transactions

sdk = load_sdk(FIREBLOCKS_API_KEY, FIREBLOCKS_PRIVATE_KEY_PATH)
txs = get_incoming_transactions(sdk, RAI_VAULT_ACCOUNT_ID, ASSET_ID, int(time.time() * 1000) - 86400000)
print(f"Connection OK. Found {len(txs)} transactions in the last 24h.")
