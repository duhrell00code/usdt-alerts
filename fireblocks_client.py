import logging
import os
from typing import Optional
from fireblocks_sdk import FireblocksSDK, TRANSACTION_STATUS_COMPLETED

logger = logging.getLogger(__name__)


def load_sdk(api_key: str, private_key_path: str, env_var: str = "FIREBLOCKS_PRIVATE_KEY") -> FireblocksSDK:
    # On Railway/cloud: set env_var with key file contents.
    # Locally: falls back to reading from the key file path.
    private_key = os.getenv(env_var)
    if not private_key:
        with open(private_key_path, "r") as f:
            private_key = f.read()
    private_key = private_key.replace("\\n", "\n")
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
    min_amount: float = 0.0,
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

    logger.info(f"Fireblocks returned {len(txs)} completed tx(s) after {after_ms}")
    results = []
    for tx in txs:
        tx_asset = tx.get("assetId")
        dest = tx.get("destination", {})
        dest_type = dest.get("type")
        dest_id = dest.get("id")
        if tx_asset != asset_id:
            logger.debug(f"  skip {tx.get('id')}: asset {tx_asset} != {asset_id}")
            continue
        if dest_type != "VAULT_ACCOUNT":
            logger.debug(f"  skip {tx.get('id')}: dest.type {dest_type!r} != VAULT_ACCOUNT")
            continue
        if dest_id != vault_account_id:
            logger.debug(f"  skip {tx.get('id')}: dest.id {dest_id!r} != {vault_account_id!r}")
            continue
        if contract_address:
            extra = tx.get("extraParameters") or {}
            if extra.get("contractAddress", "").lower() != contract_address:
                continue
        if min_amount > 0:
            amount = float(tx.get("amount") or 0)
            if amount < min_amount:
                logger.debug(f"  skip {tx.get('id')}: amount {amount} < min_amount {min_amount}")
                continue
        logger.info(f"  matched tx {tx.get('id')}")
        results.append(tx)

    return results
