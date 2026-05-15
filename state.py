import json
import os
import time


LOOKBACK_MS = 10 * 60 * 1000  # 10 minutes — covers any transactions missed during restarts


def load_state(path: str) -> dict:
    if os.path.exists(path):
        with open(path) as f:
            data = json.load(f)
        data.setdefault("last_checked_ms", _now_ms() - LOOKBACK_MS)
        data.setdefault("rstr_last_checked_ms", _now_ms() - LOOKBACK_MS)
        data.setdefault("rai_redemption_last_checked_ms", _now_ms() - LOOKBACK_MS)
        data.setdefault("testnet_last_checked_ms", _now_ms() - LOOKBACK_MS)
        data.setdefault("update_offset", 0)
        data.setdefault("pending_polls", {})
        return data
    now = _now_ms()
    return {
        "last_checked_ms": now - LOOKBACK_MS,
        "rstr_last_checked_ms": now - LOOKBACK_MS,
        "rai_redemption_last_checked_ms": now - LOOKBACK_MS,
        "testnet_last_checked_ms": now - LOOKBACK_MS,
        "update_offset": 0,
        "pending_polls": {},
    }


def save_state(path: str, state: dict) -> None:
    with open(path, "w") as f:
        json.dump(state, f)


def _now_ms() -> int:
    return int(time.time() * 1000)
