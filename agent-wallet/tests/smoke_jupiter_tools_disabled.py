"""Smoke test for temporary Jupiter Portfolio/Earn disable switch."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agent_wallet.openclaw_adapter import OpenClawWalletAdapter
from agent_wallet.wallet_layer.base import AgentWalletBackend, WalletCapabilities


class FakeBackend(AgentWalletBackend):
    name = "fake_wallet"
    network = "mainnet"

    async def get_balance(self, address: str | None = None) -> dict:
        return {"address": address or await self.get_address()}

    async def get_portfolio(self, address: str | None = None) -> dict:
        return {"address": address or await self.get_address(), "tokens": []}

    async def get_token_prices(self, mints: list[str]) -> dict:
        return {"mints": mints}

    async def get_staking_validators(self, limit: int = 20, include_delinquent: bool = False) -> dict:
        return {"limit": limit, "include_delinquent": include_delinquent, "validators": []}

    async def get_stake_account(self, stake_account: str) -> dict:
        return {"stake_account": stake_account}

    def get_capabilities(self) -> WalletCapabilities:
        return WalletCapabilities(
            backend=self.name,
            chain="solana",
            custody_model="local",
            sign_only=False,
            has_signer=True,
            can_sign_message=True,
            can_sign_transaction=True,
            can_send_transaction=True,
        )

    async def get_address(self) -> str | None:
        return "Fake11111111111111111111111111111111111111111"


async def main() -> None:
    adapter = OpenClawWalletAdapter(FakeBackend())
    tool_names = {tool.name for tool in adapter.list_tools()}
    assert "get_jupiter_portfolio" not in tool_names
    assert "get_jupiter_earn_tokens" not in tool_names
    assert "jupiter_earn_deposit" not in tool_names

    blocked = await adapter.invoke("get_jupiter_portfolio", {})
    assert blocked.ok is False
    assert "temporarily disabled" in (blocked.error or "")
    print("smoke_jupiter_tools_disabled: ok")


if __name__ == "__main__":
    asyncio.run(main())
