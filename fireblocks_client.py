import logging
import os
from typing import Optional
from fireblocks_sdk import FireblocksSDK, TRANSACTION_STATUS_COMPLETED

logger = logging.getLogger(__name__)


def load_sdk(api_key: str, private_key_path: str) -> FireblocksSDK:
    # On Railway/cloud: set FIREBLOCKS_PRIVATE_KEY env var with key file contents.
    # Locally: falls back to reading from the key file path.
    private_key = os.getenv("FIREBLOCKS_PRIVATE_KEY")
    if not private_key:
        with open(private_key_path, "r") as f:
            private_key = f.read()
    return FireblocksSDK(private_key, api_key)


def get_vault_balance(sdk: FireblocksSDK, vault_account_id: str, asset_id: str) -> float:
    """Return the total balance of asset_id in vault_account_id, or 0.0 on error."""
    try:
        asset = sdk.get_vault_account_asset(vault_account_id, asset_id)
        return float(asset.get("total", 0) or 0)
    except Exception as e:
        logger.error(f"Failed to fetch vault balance: {e}")
        return 0.0


def get_incoming_transactions(
    sdk: FireblocksSDK,
    vault_account_id: str,
    asset_id: str,
    after_ms: int,
    contract_address: Optional[str] = None,
) -> list[dict]:
    """
    Return completed INCOMING transactions to vault_account_id for asset_id
    that arrived after after_ms (Unix milliseconds).
    """
    try:
        txs = sdk.get_transactions(
            after=after_ms,
            status=TRANSACTION_STATUS_COMPLETED,
            limit=50,
        )
    except Exception as e:
        logger.error(f"Fireblocks API error: {e}")
        return []

    results = []
    for tx in txs:
        if tx.get("assetId") != asset_id:
            continue
        dest = tx.get("destination", {})
        if dest.get("type") != "VAULT_ACCOUNT":
            continue
        if dest.get("id") != vault_account_id:
            continue
        if contract_address:
            extra = tx.get("extraParameters") or {}
            if extra.get("contractAddress", "").lower() != contract_address:
                continue
        results.append(tx)

    return results
