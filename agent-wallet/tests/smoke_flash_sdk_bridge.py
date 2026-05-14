"""Smoke coverage for the Flash SDK bridge contract."""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agent_wallet.providers import flash_sdk_bridge


async def _run() -> None:
    original_env = {
        "FLASH_SDK_BRIDGE_COMMAND": os.environ.get("FLASH_SDK_BRIDGE_COMMAND"),
        "FLASH_SDK_BRIDGE_TIMEOUT_SECONDS": os.environ.get("FLASH_SDK_BRIDGE_TIMEOUT_SECONDS"),
    }
    fixture_path = Path(__file__).resolve().parent / "fixtures" / "fake_flash_sdk_bridge.py"
    try:
        os.environ["FLASH_SDK_BRIDGE_COMMAND"] = f"{sys.executable} {fixture_path}"
        os.environ["FLASH_SDK_BRIDGE_TIMEOUT_SECONDS"] = "5"

        open_preview = await flash_sdk_bridge.preview_open_position_same_collateral(
            owner="Fake11111111111111111111111111111111111111111",
            pool_name="Crypto.1",
            market_symbol="SOL",
            collateral_symbol="SOL",
            collateral_amount_raw="100000000",
            leverage="5",
            side="long",
            network="mainnet",
        )
        assert open_preview["estimated_size_usd"] == "1250.00"

        close_preview = await flash_sdk_bridge.preview_close_position_same_collateral(
            owner="Fake11111111111111111111111111111111111111111",
            pool_name="Crypto.1",
            market_symbol="SOL",
            side="long",
            network="mainnet",
        )
        assert close_preview["close_amount_raw"] == "700000000"

        print("smoke_flash_sdk_bridge: ok")
    finally:
        for key, value in original_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


if __name__ == "__main__":
    asyncio.run(_run())
