"""Smoke coverage for the repo-owned Node Flash SDK bridge in mock mode."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


def main() -> None:
    bridge_path = (
        Path(__file__).resolve().parents[1]
        / "scripts"
        / "flash-sdk-bridge"
        / "bridge.mjs"
    )
    env = dict(os.environ)
    env["FLASH_SDK_BRIDGE_MODE"] = "mock"

    payload = {
        "action": "preview_open_position_same_collateral",
        "owner": "Fake11111111111111111111111111111111111111111",
        "pool_name": "Crypto.1",
        "market_symbol": "SOL",
        "collateral_symbol": "SOL",
        "collateral_amount_raw": "100000000",
        "leverage": "5",
        "side": "long",
        "network": "mainnet",
    }

    completed = subprocess.run(
        ["node", str(bridge_path)],
        input=json.dumps(payload).encode("utf-8"),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
        check=False,
    )
    if completed.returncode != 0:
        raise AssertionError(completed.stderr.decode("utf-8", errors="replace"))
    response = json.loads(completed.stdout.decode("utf-8"))
    assert response["ok"] is True
    assert response["preview"]["bridge_mode"] == "mock"
    assert response["preview"]["estimated_size_usd"] == "1250.00"

    prepare_payload = {
        "action": "prepare_open_position_same_collateral",
        "owner": "Fake11111111111111111111111111111111111111111",
        "pool_name": "Crypto.1",
        "market_symbol": "SOL",
        "collateral_symbol": "SOL",
        "collateral_amount_raw": "100000000",
        "leverage": "5",
        "side": "long",
        "network": "mainnet",
    }
    prepared = subprocess.run(
        ["node", str(bridge_path)],
        input=json.dumps(prepare_payload).encode("utf-8"),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
        check=False,
    )
    if prepared.returncode != 0:
        raise AssertionError(prepared.stderr.decode("utf-8", errors="replace"))
    prepared_response = json.loads(prepared.stdout.decode("utf-8"))
    assert prepared_response["ok"] is True
    assert prepared_response["prepared"]["transaction_format"] == "versioned"
    print("smoke_flash_sdk_bridge_node: ok")


if __name__ == "__main__":
    main()
