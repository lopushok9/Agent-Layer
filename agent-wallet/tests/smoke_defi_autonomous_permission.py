"""Smoke test for high-trust autonomous EVM DeFi permissions."""

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
VAULT = "0xb576765fB15505433aF24FEe2c0325895C559FB2"
MARKET = "0x9103c3b4e834476c9a62ea009ba2c884ee42e94e6e314a26f04d312434191836"


class FakeDefiBackend(AgentWalletBackend):
    name = "fake_wdk_evm"
    chain = "evm"

    def __init__(self, network: str = "base") -> None:
        self.network = network

    def with_network(self, network: str) -> "FakeDefiBackend":
        return FakeDefiBackend(network)

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

    async def preview_evm_aave_operation(self, *, operation: str, token_address: str, amount_raw: str) -> dict:
        return {
            "chain": "evm",
            "network": self.network,
            "asset_type": "evm-aave-v3",
            "wallet": "fake-defi-wallet",
            "from_address": WALLET,
            "protocol": "aave-v3",
            "operation": operation,
            "token_address": token_address,
            "amount_raw": amount_raw,
            "estimated_fee_wei": "100",
            "estimated_operation_fee_wei": "70",
            "estimated_approval_fee_wei": "30",
            "quote_fingerprint": f"aave-{operation}-fingerprint",
            "allowance": {"approval_required": operation in {"supply", "repay"}},
        }

    async def send_evm_aave_operation(
        self,
        *,
        operation: str,
        token_address: str,
        amount_raw: str,
        expected_quote_fingerprint: str | None = None,
    ) -> dict:
        expected = f"aave-{operation}-fingerprint"
        if expected_quote_fingerprint != expected:
            raise WalletBackendError("missing Aave quote fingerprint")
        preview = await self.preview_evm_aave_operation(
            operation=operation,
            token_address=token_address,
            amount_raw=amount_raw,
        )
        return {**preview, "hash": "0x" + "a" * 64, "broadcasted": True, "confirmed": False}

    async def preview_evm_morpho_vault_operation(
        self,
        *,
        operation: str,
        token_address: str,
        vault_address: str | None = None,
        vault_preset: str | None = None,
        amount_raw: str | None = None,
        native_amount_raw: str | None = None,
    ) -> dict:
        return {
            "chain": "evm",
            "network": self.network,
            "asset_type": "evm-morpho-vault",
            "wallet": "fake-defi-wallet",
            "from_address": WALLET,
            "protocol": "morpho",
            "surface": "vault",
            "operation": operation,
            "target": {"vaultAddress": str(vault_address or "").lower()} if vault_address else {"vaultPreset": vault_preset},
            "token_address": token_address,
            "amount_raw": amount_raw,
            "native_amount_raw": native_amount_raw,
            "estimated_fee_wei": "100",
            "estimated_operation_fee_wei": "70",
            "estimated_requirements_fee_wei": "30",
            "quote_fingerprint": f"morpho-vault-{operation}-fingerprint",
            "requirements": {"approval_required": operation == "supply"},
        }

    async def send_evm_morpho_vault_operation(
        self,
        *,
        operation: str,
        token_address: str,
        vault_address: str | None = None,
        vault_preset: str | None = None,
        amount_raw: str | None = None,
        native_amount_raw: str | None = None,
        expected_quote_fingerprint: str | None = None,
    ) -> dict:
        expected = f"morpho-vault-{operation}-fingerprint"
        if expected_quote_fingerprint != expected:
            raise WalletBackendError("missing Morpho vault quote fingerprint")
        preview = await self.preview_evm_morpho_vault_operation(
            operation=operation,
            token_address=token_address,
            vault_address=vault_address,
            vault_preset=vault_preset,
            amount_raw=amount_raw,
            native_amount_raw=native_amount_raw,
        )
        return {**preview, "hash": "0x" + "b" * 64, "broadcasted": True, "confirmed": False}

    async def preview_evm_morpho_market_operation(
        self,
        *,
        operation: str,
        token_address: str,
        market_id: str | None = None,
        market_preset: str | None = None,
        amount_raw: str | None = None,
        native_amount_raw: str | None = None,
    ) -> dict:
        return {
            "chain": "evm",
            "network": self.network,
            "asset_type": "evm-morpho-market",
            "wallet": "fake-defi-wallet",
            "from_address": WALLET,
            "protocol": "morpho",
            "surface": "market",
            "operation": operation,
            "target": {"marketId": str(market_id or "").lower()} if market_id else {"marketPreset": market_preset},
            "token_address": token_address,
            "amount_raw": amount_raw,
            "native_amount_raw": native_amount_raw,
            "estimated_fee_wei": "100",
            "estimated_operation_fee_wei": "70",
            "estimated_requirements_fee_wei": "30",
            "quote_fingerprint": f"morpho-market-{operation}-fingerprint",
            "requirements": {"authorization_required": operation == "borrow"},
        }

    async def send_evm_morpho_market_operation(
        self,
        *,
        operation: str,
        token_address: str,
        market_id: str | None = None,
        market_preset: str | None = None,
        amount_raw: str | None = None,
        native_amount_raw: str | None = None,
        expected_quote_fingerprint: str | None = None,
    ) -> dict:
        expected = f"morpho-market-{operation}-fingerprint"
        if expected_quote_fingerprint != expected:
            raise WalletBackendError("missing Morpho market quote fingerprint")
        preview = await self.preview_evm_morpho_market_operation(
            operation=operation,
            token_address=token_address,
            market_id=market_id,
            market_preset=market_preset,
            amount_raw=amount_raw,
            native_amount_raw=native_amount_raw,
        )
        return {**preview, "hash": "0x" + "c" * 64, "broadcasted": True, "confirmed": False}

    async def preview_evm_lido_operation(self, *, operation: str, amount_raw: str) -> dict:
        return {
            "chain": "evm",
            "network": self.network,
            "asset_type": "evm-lido-staking",
            "wallet": "fake-defi-wallet",
            "from_address": WALLET,
            "protocol": "lido",
            "operation": operation,
            "amount_raw": amount_raw,
            "estimated_fee_wei": "100",
            "estimated_operation_fee_wei": "70",
            "estimated_approval_fee_wei": "30",
            "quote_fingerprint": f"lido-{operation}-fingerprint",
            "allowance": {"approval_required": operation == "wrap_steth"},
        }

    async def send_evm_lido_operation(
        self,
        *,
        operation: str,
        amount_raw: str,
        expected_quote_fingerprint: str | None = None,
    ) -> dict:
        expected = f"lido-{operation}-fingerprint"
        if expected_quote_fingerprint != expected:
            raise WalletBackendError("missing Lido quote fingerprint")
        preview = await self.preview_evm_lido_operation(operation=operation, amount_raw=amount_raw)
        return {**preview, "hash": "0x" + "d" * 64, "broadcasted": True, "confirmed": False}

    async def preview_evm_lido_withdrawal(
        self,
        *,
        operation: str,
        amount_raw: str | None = None,
        request_id: str | None = None,
    ) -> dict:
        return {
            "chain": "evm",
            "network": self.network,
            "asset_type": "evm-lido-withdrawal-queue",
            "wallet": "fake-defi-wallet",
            "from_address": WALLET,
            "protocol": "lido",
            "operation": operation,
            "amount_raw": amount_raw,
            "request_id": request_id,
            "estimated_fee_wei": "100",
            "estimated_operation_fee_wei": "70",
            "estimated_approval_fee_wei": "30",
            "quote_fingerprint": f"lido-withdrawal-{operation}-fingerprint",
            "allowance": {"approval_required": operation != "claim_withdrawal"},
        }

    async def send_evm_lido_withdrawal(
        self,
        *,
        operation: str,
        amount_raw: str | None = None,
        request_id: str | None = None,
        expected_quote_fingerprint: str | None = None,
    ) -> dict:
        expected = f"lido-withdrawal-{operation}-fingerprint"
        if expected_quote_fingerprint != expected:
            raise WalletBackendError("missing Lido withdrawal quote fingerprint")
        preview = await self.preview_evm_lido_withdrawal(
            operation=operation,
            amount_raw=amount_raw,
            request_id=request_id,
        )
        return {**preview, "hash": "0x" + "e" * 64, "broadcasted": True, "confirmed": False}

    async def preview_evm_swap(self, *, token_in: str, token_out: str, amount_in_raw: str) -> dict:
        return {
            "chain": "evm",
            "network": self.network,
            "asset_type": "evm-swap",
            "wallet": "fake-defi-wallet",
            "from_address": WALLET,
            "token_in": token_in,
            "token_out": token_out,
            "input_amount_raw": amount_in_raw,
            "quote_fingerprint": "swap-fingerprint",
        }


async def main() -> None:
    install_test_sealed_secrets(
        Path("/tmp/openclaw-defi-autonomous-smoke"),
        boot_key="test-boot-key-for-defi-autonomous-smoke",
        approval_secret="defi-autonomous-secret",
    )
    autonomous_permissions.revoke_all()

    adapter = OpenClawWalletAdapter(FakeDefiBackend("base"))

    denied = await adapter.invoke(
        "manage_evm_aave_position",
        {
            "operation": "supply",
            "token_address": USDC,
            "amount_raw": "1000000",
            "mode": "execute",
            "purpose": "autonomous defi denied",
            "network": "base",
        },
    )
    assert denied.ok is False

    rejected_approve = await adapter.invoke(
        "agentlayer_autonomous_approve",
        {"scope": "base_swaps", "purpose": "missing intent", "user_intent": False},
    )
    assert rejected_approve.ok is False

    approved = await adapter.invoke(
        "agentlayer_autonomous_approve",
        {"scope": "base_swaps", "purpose": "test combined autonomous permissions", "user_intent": True},
    )
    assert approved.ok is True
    assert approved.data["active"] is True
    assert approved.data["scopes"]["base_swaps"]["enabled"] is True
    assert approved.data["scopes"]["defi_tools"]["enabled"] is True

    aave = await adapter.invoke(
        "manage_evm_aave_position",
        {
            "operation": "borrow",
            "token_address": USDC,
            "amount_raw": "1000000",
            "mode": "execute",
            "purpose": "autonomous aave borrow",
            "network": "base",
        },
    )
    assert aave.ok is True
    assert aave.data["hash"].startswith("0x")

    morpho_vault = await adapter.invoke(
        "manage_evm_morpho_vault_position",
        {
            "operation": "withdraw",
            "token_address": USDC,
            "vault_address": VAULT,
            "amount_raw": "2500000",
            "mode": "execute",
            "purpose": "autonomous morpho vault withdraw",
            "network": "base",
        },
    )
    assert morpho_vault.ok is True
    assert morpho_vault.data["hash"].startswith("0x")

    morpho_market = await adapter.invoke(
        "manage_evm_morpho_market_position",
        {
            "operation": "withdraw_collateral",
            "token_address": USDC,
            "market_id": MARKET,
            "amount_raw": "500000",
            "mode": "execute",
            "purpose": "autonomous morpho market withdraw collateral",
            "network": "base",
        },
    )
    assert morpho_market.ok is True
    assert morpho_market.data["hash"].startswith("0x")

    lido = await adapter.invoke(
        "manage_evm_lido_position",
        {
            "operation": "wrap_steth",
            "amount_raw": "1000000000000000000",
            "mode": "execute",
            "purpose": "autonomous lido wrap",
            "network": "ethereum",
        },
    )
    assert lido.ok is True
    assert lido.data["hash"].startswith("0x")

    lido_withdrawal = await adapter.invoke(
        "manage_evm_lido_withdrawal",
        {
            "operation": "claim_withdrawal",
            "request_id": "102",
            "mode": "execute",
            "purpose": "autonomous lido claim",
            "network": "ethereum",
        },
    )
    assert lido_withdrawal.ok is True
    assert lido_withdrawal.data["hash"].startswith("0x")

    revoked = await adapter.invoke("agentlayer_autonomous_revoke", {"scope": "base_swaps"})
    assert revoked.ok is True
    assert revoked.data["active"] is False
    assert revoked.data["scopes"]["base_swaps"]["enabled"] is False
    assert revoked.data["scopes"]["defi_tools"]["enabled"] is False

    after_revoke = await adapter.invoke(
        "manage_evm_aave_position",
        {
            "operation": "supply",
            "token_address": USDC,
            "amount_raw": "1000000",
            "mode": "execute",
            "purpose": "autonomous defi revoked",
            "network": "base",
        },
    )
    assert after_revoke.ok is False

    print("smoke_defi_autonomous_permission: ok")


if __name__ == "__main__":
    asyncio.run(main())
