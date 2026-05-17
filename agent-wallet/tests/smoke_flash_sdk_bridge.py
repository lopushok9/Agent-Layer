"""Smoke coverage for the Flash SDK bridge contract."""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agent_wallet.providers import flash_sdk_bridge


async def _inspect_bridge_env() -> dict[str, str | None]:
    return await flash_sdk_bridge._call_bridge(  # type: ignore[attr-defined]
        {
            "action": "inspect_env",
            "network": "mainnet",
        }
    )


async def _run() -> None:
    original_env = {
        "FLASH_SDK_BRIDGE_COMMAND": os.environ.get("FLASH_SDK_BRIDGE_COMMAND"),
        "FLASH_SDK_BRIDGE_MODE": os.environ.get("FLASH_SDK_BRIDGE_MODE"),
        "SOLANA_RPC_URL": os.environ.get("SOLANA_RPC_URL"),
        "RPC_URL": os.environ.get("RPC_URL"),
        "FLASH_SDK_BRIDGE_TIMEOUT_SECONDS": os.environ.get("FLASH_SDK_BRIDGE_TIMEOUT_SECONDS"),
    }
    fixture_path = Path(__file__).resolve().parent / "fixtures" / "fake_flash_sdk_bridge.py"
    try:
        os.environ["FLASH_SDK_BRIDGE_COMMAND"] = f"{sys.executable} {fixture_path}"
        os.environ["FLASH_SDK_BRIDGE_MODE"] = "real"
        os.environ.pop("SOLANA_RPC_URL", None)
        os.environ.pop("RPC_URL", None)
        os.environ["FLASH_SDK_BRIDGE_TIMEOUT_SECONDS"] = "5"

        env_probe = await _inspect_bridge_env()
        assert env_probe["data"]["flash_sdk_bridge_mode"] == "real"
        assert env_probe["data"]["solana_rpc_url"] == "https://api.mainnet-beta.solana.com"

        open_preview = await flash_sdk_bridge.preview_open_position(
            owner="Fake11111111111111111111111111111111111111111",
            pool_name="Crypto.1",
            market_symbol="SOL",
            collateral_symbol="USDC",
            collateral_amount_raw="5000000",
            leverage="2",
            side="short",
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

        open_prepare = await flash_sdk_bridge.prepare_open_position(
            owner="Fake11111111111111111111111111111111111111111",
            pool_name="Crypto.1",
            market_symbol="SOL",
            collateral_symbol="USDC",
            collateral_amount_raw="5000000",
            leverage="2",
            side="short",
            network="mainnet",
        )
        assert open_prepare["transaction_format"] == "versioned"

        close_prepare = await flash_sdk_bridge.prepare_close_position_same_collateral(
            owner="Fake11111111111111111111111111111111111111111",
            pool_name="Crypto.1",
            market_symbol="SOL",
            side="long",
            network="mainnet",
        )
        assert close_prepare["position_address"] == "FakeFlashPosition111111111111111111111111111"

        print("smoke_flash_sdk_bridge: ok")
    finally:
        for key, value in original_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


if __name__ == "__main__":
    asyncio.run(_run())
