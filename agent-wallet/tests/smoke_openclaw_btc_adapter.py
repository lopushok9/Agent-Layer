"""Smoke test for the OpenClaw BTC adapter surface."""

from __future__ import annotations

import asyncio
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from _secret_test_utils import install_test_sealed_secrets  # noqa: E402
from agent_wallet.approval import issue_approval_token  # noqa: E402
from agent_wallet.openclaw_adapter import OpenClawWalletAdapter  # noqa: E402
from agent_wallet.wallet_layer.base import AgentWalletBackend, WalletCapabilities  # noqa: E402


class FakeBtcBackend(AgentWalletBackend):
    name = "wdk_btc_local"
    chain = "bitcoin"
    network = "bitcoin"
    sign_only = False

    async def get_address(self) -> str | None:
        return "bc1qadapter000000000000000000000000000000000"

    async def get_balance(self, address: str | None = None) -> dict:
        return {
            "chain": "bitcoin",
            "network": "bitcoin",
            "address": address or await self.get_address(),
            "balance_sats": 121140,
            "balance_native": 0.0012114,
            "asset": "BTC",
            "source": "fake",
        }

    async def get_btc_transfer_history(
        self,
        *,
        direction: str = "all",
        limit: int = 10,
        skip: int = 0,
    ) -> dict:
        return {
            "chain": "bitcoin",
            "network": "bitcoin",
            "address": await self.get_address(),
            "direction": direction,
            "limit": limit,
            "skip": skip,
            "transfers": [{"hash": "incoming-hash", "direction": direction}],
            "source": "fake",
        }

    async def get_btc_fee_rates(self) -> dict:
        return {
            "chain": "bitcoin",
            "network": "bitcoin",
            "fee_rates": {"slow": 1, "normal": 2, "fast": 3},
            "source": "fake",
        }

    async def get_btc_max_spendable(self, *, fee_rate: int | None = None) -> dict:
        return {
            "chain": "bitcoin",
            "network": "bitcoin",
            "address": await self.get_address(),
            "fee_rate": fee_rate,
            "amount_sats": 120699,
            "amount_btc": 0.00120699,
            "estimated_fee_sats": 141 if fee_rate is None else 423,
            "estimated_fee_btc": 0.00000141 if fee_rate is None else 0.00000423,
            "change_sats": 300,
            "change_btc": 0.000003,
            "source": "fake",
        }

    async def preview_btc_transfer(
        self,
        *,
        recipient: str,
        amount_sats: int,
        fee_rate: int | None = None,
        confirmation_target: int | None = None,
    ) -> dict:
        return {
            "chain": "bitcoin",
            "network": "bitcoin",
            "asset_type": "btc-transfer",
            "asset": "BTC",
            "wallet": "btc-wallet-123",
            "from_address": await self.get_address(),
            "recipient": recipient,
            "amount_sats": amount_sats,
            "amount_btc": amount_sats / 100_000_000,
            "fee_rate": fee_rate,
            "confirmation_target": confirmation_target,
            "estimated_fee_sats": 141 if fee_rate is None else 423,
            "estimated_fee_btc": 0.00000141 if fee_rate is None else 0.00000423,
            "source": "fake",
        }

    async def send_btc_transfer(
        self,
        *,
        recipient: str,
        amount_sats: int,
        fee_rate: int | None = None,
        confirmation_target: int | None = None,
    ) -> dict:
        preview = await self.preview_btc_transfer(
            recipient=recipient,
            amount_sats=amount_sats,
            fee_rate=fee_rate,
            confirmation_target=confirmation_target,
        )
        return {
            **preview,
            "hash": "btc-test-hash",
            "broadcasted": True,
            "confirmed": False,
        }

    def get_capabilities(self) -> WalletCapabilities:
        return WalletCapabilities(
            backend=self.name,
            chain=self.chain,
            custody_model="local_service_vault",
            sign_only=False,
            has_signer=True,
            can_get_address=True,
            can_get_balance=True,
            can_sign_message=False,
            can_sign_transaction=True,
            can_send_transaction=True,
            external_dependencies=["wdk-btc-wallet"],
        )


async def _main() -> None:
    adapter = OpenClawWalletAdapter(FakeBtcBackend())
    tool_names = {tool.name for tool in adapter.list_tools()}
    assert "transfer_btc" in tool_names
    assert "get_btc_fee_rates" in tool_names
    assert "transfer_sol" not in tool_names

    balance = await adapter.invoke("get_wallet_balance", {})
    assert balance.ok is True
    assert balance.data["balance_sats"] == 121140

    preview = await adapter.invoke(
        "transfer_btc",
        {
            "recipient": "bc1qdest000000000000000000000000000000000000",
            "amount_sats": 10_000,
            "mode": "preview",
            "purpose": "test btc transfer",
        },
    )
    assert preview.ok is True
    assert preview.data["estimated_fee_sats"] == 141

    prepared = await adapter.invoke(
        "transfer_btc",
        {
            "recipient": "bc1qdest000000000000000000000000000000000000",
            "amount_sats": 10_000,
            "fee_rate": 3,
            "mode": "prepare",
            "purpose": "test btc transfer",
            "user_intent": True,
        },
    )
    assert prepared.ok is True
    assert prepared.data["execution_plan_only"] is True

    approval = issue_approval_token(
        tool_name="transfer_btc",
        network="bitcoin",
        summary=preview.data["confirmation_summary"],
        mainnet_confirmed=True,
        issued_by="test",
    )
    executed = await adapter.invoke(
        "transfer_btc",
        {
            "recipient": "bc1qdest000000000000000000000000000000000000",
            "amount_sats": 10_000,
            "mode": "execute",
            "purpose": "test btc transfer",
            "approval_token": approval,
        },
    )
    assert executed.ok is True
    assert executed.data["hash"] == "btc-test-hash"


def main() -> None:
    temp_home = Path("/tmp/openclaw-btc-adapter-smoke")
    if temp_home.exists():
        shutil.rmtree(temp_home)
    install_test_sealed_secrets(
        temp_home,
        boot_key="test-boot-key-for-btc-adapter-smoke",
        master_key="test-master-key-for-btc-adapter-smoke",
        approval_secret="test-approval-secret-for-btc-adapter-smoke",
    )
    asyncio.run(_main())
    print("smoke_openclaw_btc_adapter: ok")


if __name__ == "__main__":
    main()
