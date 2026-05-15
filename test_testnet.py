import time
from config import TESTNET_API_KEY, TESTNET_PRIVATE_KEY_PATH, TESTNET_VAULT_ACCOUNT_ID, TESTNET_ASSET_ID
from fireblocks_client import load_sdk

sdk = load_sdk(TESTNET_API_KEY, TESTNET_PRIVATE_KEY_PATH)

after_ms = int(time.time() * 1000) - 24 * 3600 * 1000  # last 24 hours

print(f"Fetching ALL transactions (no status filter) for last 24h...")
txs = sdk.get_transactions(after=after_ms, limit=50)
print(f"Total transactions: {len(txs)}\n")

for tx in txs:
    dest = tx.get("destination", {})
    print(f"ID:          {tx.get('id')}")
    print(f"Status:      {tx.get('status')}")
    print(f"Asset:       {tx.get('assetId')}")
    print(f"dest.type:   {dest.get('type')!r}")
    print(f"dest.id:     {dest.get('id')!r}  (type: {type(dest.get('id')).__name__})")
    print(f"vault_id:    {TESTNET_VAULT_ACCOUNT_ID!r}  (type: {type(TESTNET_VAULT_ACCOUNT_ID).__name__})")
    print(f"asset match: {tx.get('assetId') == TESTNET_ASSET_ID}")
    print(f"dest match:  {str(dest.get('id')) == str(TESTNET_VAULT_ACCOUNT_ID)}")
    print()
