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
        "action": "preview_open_position",
        "owner": "Fake11111111111111111111111111111111111111111",
        "pool_name": "Crypto.1",
        "market_symbol": "SOL",
        "collateral_symbol": "USDC",
        "collateral_amount_raw": "5000000",
        "leverage": "2",
        "side": "short",
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

    markets = subprocess.run(
        ["node", str(bridge_path)],
        input=json.dumps(
            {
                "action": "get_markets",
                "pool_name": "Crypto.1",
                "network": "mainnet",
            }
        ).encode("utf-8"),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
        check=False,
    )
    if markets.returncode != 0:
        raise AssertionError(markets.stderr.decode("utf-8", errors="replace"))
    markets_response = json.loads(markets.stdout.decode("utf-8"))
    assert markets_response["ok"] is True
    assert markets_response["data"]["market_count"] == 2
    assert markets_response["data"]["markets"][1]["collateral_symbol"] == "USDC"

    real_env = dict(os.environ)
    real_env["FLASH_SDK_BRIDGE_MODE"] = "real"
    real_markets = subprocess.run(
        ["node", str(bridge_path)],
        input=json.dumps(
            {
                "action": "get_markets",
                "network": "mainnet",
            }
        ).encode("utf-8"),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=real_env,
        check=False,
    )
    if real_markets.returncode != 0:
        raise AssertionError(real_markets.stderr.decode("utf-8", errors="replace"))
    real_markets_response = json.loads(real_markets.stdout.decode("utf-8"))
    assert real_markets_response["ok"] is True
    assert real_markets_response["data"]["market_count"] > 0
    real_symbols = {
        str(item.get("market_symbol") or "").strip()
        for item in real_markets_response["data"]["markets"]
        if isinstance(item, dict)
    }
    assert "SOL" in real_symbols

    positions = subprocess.run(
        ["node", str(bridge_path)],
        input=json.dumps(
            {
                "action": "get_positions",
                "owner": "Fake11111111111111111111111111111111111111111",
                "pool_name": "Crypto.1",
                "network": "mainnet",
            }
        ).encode("utf-8"),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
        check=False,
    )
    if positions.returncode != 0:
        raise AssertionError(positions.stderr.decode("utf-8", errors="replace"))
    positions_response = json.loads(positions.stdout.decode("utf-8"))
    assert positions_response["ok"] is True
    assert positions_response["data"]["position_count"] == 1

    prepare_payload = {
        "action": "prepare_open_position",
        "owner": "Fake11111111111111111111111111111111111111111",
        "pool_name": "Crypto.1",
        "market_symbol": "SOL",
        "collateral_symbol": "USDC",
        "collateral_amount_raw": "5000000",
        "leverage": "2",
        "side": "short",
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
