"""Smoke test for high-trust autonomous Base swap permissions."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from _secret_test_utils import install_test_sealed_secrets  # noqa: E402
from agent_wallet import autonomous_permissions  # noqa: E402
from agent_wallet.openclaw_adapter import OpenClawWalletAdapter  # noqa: E402
from agent_wallet.wallet_layer.base import AgentWalletBackend, WalletCapabilities, WalletBackendError  # noqa: E402

WALLET = "0x1111111111111111111111111111111111111111"
USDC = "0x2222222222222222222222222222222222222222"
USDT = "0x3333333333333333333333333333333333333333"


class FakeBaseSwapBackend(AgentWalletBackend):
    name = "fake_wdk_evm"
    chain = "evm"

    def __init__(self, network: str = "base") -> None:
        self.network = network
        self.velora_sends = 0
        self.uniswap_sends = 0

    async def get_address(self) -> str | None:
        return WALLET

    async def get_balance(self, address: str | None = None) -> dict:
        return {"chain": "evm", "network": self.network, "address": address or WALLET}

    def get_capabilities(self) -> WalletCapabilities:
        return WalletCapabilities(
            backend=self.name,
            chain=self.chain,
            custody_model="local_service_vault",
            sign_only=False,
            has_signer=True,
            can_send_transaction=True,
        )

    async def preview_evm_swap(self, *, token_in: str, token_out: str, amount_in_raw: str) -> dict:
        return {
            "chain": "evm",
            "network": self.network,
            "asset_type": "evm-swap",
            "wallet": "fake-base-wallet",
            "from_address": WALLET,
            "token_in": token_in,
            "token_out": token_out,
            "input_amount_raw": amount_in_raw,
            "estimated_output_amount_raw": "995000",
            "minimum_output_amount_raw": "985050",
            "slippage_bps": 100,
            "swap_provider": "velora",
            "quote_fingerprint": "velora-fingerprint",
            "router": "0x4444444444444444444444444444444444444444",
            "swap_transaction": {"to": "0x4444444444444444444444444444444444444444", "data_hash": "velora-data"},
        }

    async def send_evm_swap(
        self,
        *,
        token_in: str,
        token_out: str,
        amount_in_raw: str,
        expected_quote_fingerprint: str | None = None,
        minimum_output_amount_raw: str | None = None,
    ) -> dict:
        if expected_quote_fingerprint != "velora-fingerprint":
            raise WalletBackendError("missing Velora quote fingerprint")
        if minimum_output_amount_raw != "985050":
            raise WalletBackendError("missing Velora minimum output")
        self.velora_sends += 1
        preview = await self.preview_evm_swap(token_in=token_in, token_out=token_out, amount_in_raw=amount_in_raw)
        return {**preview, "hash": "0x" + "a" * 64, "broadcasted": True, "confirmed": True}

    async def preview_uniswap_swap(
        self,
        *,
        token_in: str,
        token_out: str,
        amount_in_raw: str,
        slippage_bps: int | None = None,
    ) -> dict:
        return {
            "chain": "evm",
            "network": self.network,
            "asset_type": "evm-uniswap-swap",
            "wallet": "fake-base-wallet",
            "from_address": WALLET,
            "swap_provider": "uniswap",
            "routing": "CLASSIC",
            "token_in": token_in,
            "token_out": token_out,
            "input_amount_raw": amount_in_raw,
            "estimated_output_amount_raw": "994000",
            "minimum_output_amount_raw": "980000",
            "slippage_bps": slippage_bps,
            "permit_required": True,
            "router": "0x5555555555555555555555555555555555555555",
            "quote_fingerprint": "uniswap-fingerprint",
        }

    async def send_uniswap_swap(
        self,
        *,
        token_in: str,
        token_out: str,
        amount_in_raw: str,
        slippage_bps: int | None = None,
        expected_quote_fingerprint: str | None = None,
        minimum_output_amount_raw: str | None = None,
    ) -> dict:
        if expected_quote_fingerprint != "uniswap-fingerprint":
            raise WalletBackendError("missing Uniswap quote fingerprint")
        if minimum_output_amount_raw != "980000":
            raise WalletBackendError("missing Uniswap minimum output")
        self.uniswap_sends += 1
        preview = await self.preview_uniswap_swap(
            token_in=token_in,
            token_out=token_out,
            amount_in_raw=amount_in_raw,
            slippage_bps=slippage_bps,
        )
        return {**preview, "hash": "0x" + "b" * 64, "broadcasted": True, "confirmed": True}

    async def preview_evm_native_transfer(self, *, recipient: str, amount_wei: str) -> dict:
        return {"chain": "evm", "network": self.network, "recipient": recipient, "amount_wei": amount_wei}

    async def send_evm_native_transfer(self, *, recipient: str, amount_wei: str) -> dict:
        return {"chain": "evm", "network": self.network, "recipient": recipient, "amount_wei": amount_wei}


def _velora_args() -> dict:
    return {
        "token_in": USDC,
        "token_out": USDT,
        "amount_in_raw": "1000000",
        "mode": "execute",
        "purpose": "autonomous base velora smoke",
    }


def _uniswap_args() -> dict:
    return {
        "token_in": USDC,
        "token_out": USDT,
        "amount_in_raw": "1000000",
        "slippage_bps": 50,
        "mode": "execute",
        "purpose": "autonomous base uniswap smoke",
    }


async def main() -> None:
    install_test_sealed_secrets(
        Path("/tmp/openclaw-base-swap-autonomous-smoke"),
        boot_key="test-boot-key-for-base-swap-autonomous-smoke",
        approval_secret="base-swap-autonomous-secret",
    )
    autonomous_permissions.revoke_all()

    backend = FakeBaseSwapBackend("base")
    adapter = OpenClawWalletAdapter(backend)
    tool_names = {tool.name for tool in adapter.list_tools()}
    assert "agentlayer_autonomous_approve" in tool_names
    assert "agentlayer_autonomous_revoke" in tool_names
    assert "agentlayer_autonomous_status" in tool_names

    no_permission = await adapter.invoke("swap_evm_tokens", _velora_args())
    assert no_permission.ok is False
    assert backend.velora_sends == 0

    rejected_approve = await adapter.invoke(
        "agentlayer_autonomous_approve",
        {"scope": "base_swaps", "purpose": "test missing user intent", "user_intent": False},
    )
    assert rejected_approve.ok is False

    approved = await adapter.invoke(
        "agentlayer_autonomous_approve",
        {"scope": "base_swaps", "purpose": "test base swaps", "user_intent": True},
    )
    assert approved.ok is True
    assert approved.data["active"] is True
    assert approved.data["scopes"]["base_swaps"]["enabled"] is True
    assert approved.data["scopes"]["defi_tools"]["enabled"] is True

    velora = await adapter.invoke("swap_evm_tokens", _velora_args())
    assert velora.ok is True
    assert velora.data["hash"].startswith("0x")
    assert backend.velora_sends == 1

    uniswap = await adapter.invoke("swap_evm_uniswap_tokens", _uniswap_args())
    assert uniswap.ok is True
    assert uniswap.data["hash"].startswith("0x")
    assert backend.uniswap_sends == 1

    # agentlayer_autonomous_approve now covers every write tool that funnels
    # through _require_execute_approval (the shared choke point), not just
    # the Base-swap/EVM-DeFi tools that have their own dedicated
    # pre-authorization step ahead of it.
    transfer = await adapter.invoke(
        "transfer_evm_native",
        {
            "recipient": "0x9999999999999999999999999999999999999999",
            "amount_wei": "1000000000000000",
            "mode": "execute",
            "purpose": "covered by the combined autonomous permission group",
        },
    )
    assert transfer.ok is True
    assert transfer.data["recipient"] == "0x9999999999999999999999999999999999999999"

    ethereum_adapter = OpenClawWalletAdapter(FakeBaseSwapBackend("ethereum"))
    wrong_network = await ethereum_adapter.invoke("swap_evm_tokens", _velora_args())
    assert wrong_network.ok is False
    assert "network=base" in (wrong_network.error or "")

    revoked = await adapter.invoke("agentlayer_autonomous_revoke", {"scope": "base_swaps"})
    assert revoked.ok is True
    assert revoked.data["active"] is False
    assert revoked.data["scopes"]["base_swaps"]["enabled"] is False
    assert revoked.data["scopes"]["defi_tools"]["enabled"] is False
    after_revoke = await adapter.invoke("swap_evm_tokens", _velora_args())
    assert after_revoke.ok is False

    transfer_after_revoke = await adapter.invoke(
        "transfer_evm_native",
        {
            "recipient": "0x9999999999999999999999999999999999999999",
            "amount_wei": "1000000000000000",
            "mode": "execute",
            "purpose": "must require approval again after revoke",
        },
    )
    assert transfer_after_revoke.ok is False

    print("smoke_base_swap_autonomous_permission: ok")


if __name__ == "__main__":
    asyncio.run(main())
