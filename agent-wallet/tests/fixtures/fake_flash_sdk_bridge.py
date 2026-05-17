"""Fake Flash SDK bridge used by smoke tests."""

from __future__ import annotations

import json
import os
import sys


def main() -> int:
    payload = json.loads(sys.stdin.read() or "{}")
    action = payload.get("action")

    if action in {"preview_open_position", "preview_open_position_same_collateral"}:
        response = {
            "ok": True,
            "preview": {
                "estimated_size_usd": "1250.00",
                "estimated_entry_price": "177.50",
                "estimated_liquidation_price": "161.20",
            },
        }
        print(json.dumps(response))
        return 0

    if action == "preview_close_position_same_collateral":
        response = {
            "ok": True,
            "preview": {
                "position_size_usd": "1250.00",
                "close_amount_raw": "700000000",
            },
        }
        print(json.dumps(response))
        return 0

    if action in {"prepare_open_position", "prepare_open_position_same_collateral"}:
        response = {
            "ok": True,
            "prepared": {
                "transaction_base64": "AQID",
                "transaction_encoding": "base64",
                "transaction_format": "versioned",
                "last_valid_block_height": 123,
                "latest_blockhash": "FakeBlockhash111111111111111111111111111111",
                "market_address": "FakeFlashMarket11111111111111111111111111111",
                "position_address": "FakeFlashPosition111111111111111111111111111",
                "target_custody_address": "FakeFlashTargetCustody1111111111111111111111111",
                "collateral_custody_address": "FakeFlashCollateralCustody1111111111111111111111",
                "collateral_mint": "So11111111111111111111111111111111111111112",
                "expected_program_ids": ["FakeFlashProgram111111111111111111111111111111"],
            },
        }
        print(json.dumps(response))
        return 0

    if action == "prepare_close_position_same_collateral":
        response = {
            "ok": True,
            "prepared": {
                "transaction_base64": "AQID",
                "transaction_encoding": "base64",
                "transaction_format": "versioned",
                "last_valid_block_height": 123,
                "latest_blockhash": "FakeBlockhash111111111111111111111111111111",
                "market_address": "FakeFlashMarket11111111111111111111111111111",
                "position_address": "FakeFlashPosition111111111111111111111111111",
                "target_custody_address": "FakeFlashTargetCustody1111111111111111111111111",
                "collateral_custody_address": "FakeFlashCollateralCustody1111111111111111111111",
                "collateral_mint": "So11111111111111111111111111111111111111112",
                "expected_program_ids": ["FakeFlashProgram111111111111111111111111111111"],
            },
        }
        print(json.dumps(response))
        return 0

    if action == "inspect_env":
        response = {
            "ok": True,
            "data": {
                "flash_sdk_bridge_mode": os.environ.get("FLASH_SDK_BRIDGE_MODE"),
                "solana_rpc_url": os.environ.get("SOLANA_RPC_URL"),
                "rpc_url": os.environ.get("RPC_URL"),
            },
        }
        print(json.dumps(response))
        return 0

    print(json.dumps({"ok": False, "error": f"Unsupported action: {action}"}))
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
