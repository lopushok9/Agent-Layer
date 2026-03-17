"""Smoke test for host-issued wallet approval tokens."""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from _secret_test_utils import install_test_sealed_secrets  # noqa: E402
from agent_wallet.approval import issue_approval_token
from agent_wallet.openclaw_adapter import OpenClawWalletAdapter
from agent_wallet.wallet_layer.base import AgentWalletBackend, WalletCapabilities


class FakeBackend(AgentWalletBackend):
    name = "fake_wallet"
    network = "mainnet"

    async def get_address(self) -> str | None:
        return "Fake11111111111111111111111111111111111111111"

    async def get_balance(self, address: str | None = None) -> dict:
        return {"chain": "solana", "network": "mainnet", "address": address or await self.get_address()}

    def get_capabilities(self) -> WalletCapabilities:
        return WalletCapabilities(
            backend=self.name,
            chain="solana",
            custody_model="local",
            sign_only=False,
            has_signer=True,
            can_send_transaction=True,
        )

    async def preview_native_transfer(self, recipient: str, amount_native: float) -> dict:
        return {
            "chain": "solana",
            "network": "mainnet",
            "mode": "preview",
            "from_address": "Fake11111111111111111111111111111111111111111",
            "to_address": recipient,
            "amount_native": amount_native,
            "source": "fake",
        }

    async def send_native_transfer(self, recipient: str, amount_native: float) -> dict:
        return {
            "chain": "solana",
            "network": "mainnet",
            "mode": "execute",
            "from_address": "Fake11111111111111111111111111111111111111111",
            "to_address": recipient,
            "amount_native": amount_native,
            "signature": "ok",
            "broadcasted": True,
            "confirmed": True,
            "source": "fake",
        }


async def main() -> None:
    install_test_sealed_secrets(
        Path("/tmp/openclaw-wallet-approval-smoke"),
        boot_key="test-boot-key-for-wallet-approval-smoke",
        approval_secret="smoke-approval-secret",
    )
    adapter = OpenClawWalletAdapter(FakeBackend())

    preview = await adapter.invoke(
        "transfer_sol",
        {
            "recipient": "FakeRecipient1111111111111111111111111111111111",
            "amount": 0.25,
            "mode": "preview",
            "purpose": "smoke preview",
        },
    )
    assert preview.ok is True

    denied = await adapter.invoke(
        "transfer_sol",
        {
            "recipient": "FakeRecipient1111111111111111111111111111111111",
            "amount": 0.25,
            "mode": "execute",
            "purpose": "smoke execute",
        },
    )
    assert denied.ok is False

    token = issue_approval_token(
        tool_name="transfer_sol",
        network="mainnet",
        summary=preview.data["confirmation_summary"],
        mainnet_confirmed=True,
        ttl_seconds=300,
        issued_by="smoke-test",
    )

    allowed = await adapter.invoke(
        "transfer_sol",
        {
            "recipient": "FakeRecipient1111111111111111111111111111111111",
            "amount": 0.25,
            "mode": "execute",
            "purpose": "smoke execute",
            "approval_token": token,
        },
    )
    assert allowed.ok is True
    assert allowed.data["confirmed"] is True

    replayed = await adapter.invoke(
        "transfer_sol",
        {
            "recipient": "FakeRecipient1111111111111111111111111111111111",
            "amount": 0.25,
            "mode": "execute",
            "purpose": "smoke replay",
            "approval_token": token,
        },
    )
    assert replayed.ok is False
    assert "already been used" in (replayed.error or "")

    print("smoke_wallet_approval: ok")


if __name__ == "__main__":
    asyncio.run(main())
