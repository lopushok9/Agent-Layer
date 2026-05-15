"""Smoke coverage for Flash mock prepare on the real Solana backend path."""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agent_wallet.exceptions import ProviderError
from agent_wallet.providers import flash
from agent_wallet.wallet_layer.base import WalletBackendError
from agent_wallet.wallet_layer.solana import SolanaLocalKeypairSigner, SolanaWalletBackend


def _build_signer() -> SolanaLocalKeypairSigner:
    secret = "[" + ",".join(str(index) for index in range(1, 33)) + "]"
    return SolanaLocalKeypairSigner.from_secret_material(secret)


async def _fail_provider(*args, **kwargs):
    raise ProviderError("flash-trade", "forced smoke fallback")


async def _run() -> None:
    original_env = {
        "FLASH_SDK_BRIDGE_COMMAND": os.environ.get("FLASH_SDK_BRIDGE_COMMAND"),
        "FLASH_SDK_BRIDGE_MODE": os.environ.get("FLASH_SDK_BRIDGE_MODE"),
        "FLASH_SDK_BRIDGE_TIMEOUT_SECONDS": os.environ.get("FLASH_SDK_BRIDGE_TIMEOUT_SECONDS"),
    }
    original_fetch_markets = flash.fetch_markets
    original_fetch_positions = flash.fetch_positions
    bridge_path = (
        Path(__file__).resolve().parents[1] / "scripts" / "flash-sdk-bridge" / "bridge.mjs"
    )
    try:
        os.environ["FLASH_SDK_BRIDGE_COMMAND"] = f"node {bridge_path}"
        os.environ["FLASH_SDK_BRIDGE_MODE"] = "mock"
        os.environ["FLASH_SDK_BRIDGE_TIMEOUT_SECONDS"] = "5"
        flash.fetch_markets = _fail_provider
        flash.fetch_positions = _fail_provider

        backend = SolanaWalletBackend(
            rpc_url="https://api.mainnet-beta.solana.com",
            network="mainnet",
            signer=_build_signer(),
            sign_only=False,
        )

        markets = await backend.get_flash_trade_markets(pool_name="Crypto.1")
        assert markets["source"] == "flash-sdk-bridge"
        assert markets["market_count"] >= 1

        positions = await backend.get_flash_trade_positions(pool_name="Crypto.1")
        assert positions["source"] == "flash-sdk-bridge"
        assert positions["position_count"] >= 1

        open_prepare = await backend.prepare_flash_trade_open_position(
            pool_name="Crypto.1",
            market_symbol="SOL",
            collateral_symbol="SOL",
            collateral_amount_raw="100000000",
            leverage="5",
            side="long",
        )
        assert open_prepare["bridge_mode"] == "mock"
        assert open_prepare["mock_prepare_only"] is True
        assert open_prepare["signed"] is False

        close_prepare = await backend.prepare_flash_trade_close_position(
            pool_name="Crypto.1",
            market_symbol="SOL",
            side="long",
        )
        assert close_prepare["bridge_mode"] == "mock"
        assert close_prepare["mock_prepare_only"] is True

        try:
            await backend.execute_flash_trade_open_position(
                pool_name="Crypto.1",
                market_symbol="SOL",
                collateral_symbol="SOL",
                collateral_amount_raw="100000000",
                leverage="5",
                side="long",
            )
        except WalletBackendError as exc:
            assert "FLASH_SDK_BRIDGE_MODE=mock" in str(exc)
        else:
            raise AssertionError("Mock execute should be rejected.")

        print("smoke_flash_prepare_mock_backend: ok")
    finally:
        flash.fetch_markets = original_fetch_markets
        flash.fetch_positions = original_fetch_positions
        for key, value in original_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


if __name__ == "__main__":
    asyncio.run(_run())
