"""Smoke test for the OpenClaw EVM adapter surface."""

from __future__ import annotations

import asyncio
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from _secret_test_utils import install_test_sealed_secrets  # noqa: E402
from agent_wallet.approval import issue_approval_token  # noqa: E402
from agent_wallet.openclaw_adapter import OpenClawWalletAdapter  # noqa: E402
from agent_wallet.wallet_layer.base import AgentWalletBackend, WalletBackendError, WalletCapabilities  # noqa: E402


class FakeEvmBackend(AgentWalletBackend):
    name = "wdk_evm_local"
    chain = "evm"
    network = "sepolia"
    sign_only = False

    async def get_address(self) -> str | None:
        return "0x1111111111111111111111111111111111111111"

    async def get_balance(self, address: str | None = None) -> dict:
        return {
            "chain": "evm",
            "network": "sepolia",
            "address": address or await self.get_address(),
            "balance_wei": "1230000000000000000",
            "balance_native": "1.23",
            "asset": "ETH",
            "source": "fake",
        }

    async def get_evm_token_balance(self, token_address: str) -> dict:
        return {
            "chain": "evm",
            "network": "sepolia",
            "address": await self.get_address(),
            "token_address": token_address,
            "balance_raw": "42000000",
            "source": "fake",
        }

    async def get_evm_fee_rates(self) -> dict:
        return {
            "chain": "evm",
            "network": "sepolia",
            "fee_rates": {
                "slow": "1200000000",
                "normal": "2000000000",
                "fast": "3000000000",
            },
            "source": "fake",
        }

    async def get_evm_transaction_receipt(self, tx_hash: str) -> dict:
        return {
            "chain": "evm",
            "network": "sepolia",
            "tx_hash": tx_hash,
            "found": True,
            "receipt": {"transactionHash": tx_hash, "status": "0x1"},
            "source": "fake",
        }

    async def preview_evm_native_transfer(
        self,
        *,
        recipient: str,
        amount_wei: str,
    ) -> dict:
        return {
            "chain": "evm",
            "network": "sepolia",
            "asset_type": "evm-native-transfer",
            "asset": "ETH",
            "wallet": "evm-wallet-123",
            "from_address": await self.get_address(),
            "recipient": recipient,
            "amount_wei": amount_wei,
            "estimated_fee_wei": "21000000000000",
            "source": "fake",
        }

    async def send_evm_native_transfer(
        self,
        *,
        recipient: str,
        amount_wei: str,
    ) -> dict:
        preview = await self.preview_evm_native_transfer(recipient=recipient, amount_wei=amount_wei)
        return {
            **preview,
            "hash": "0x" + "b" * 64,
            "broadcasted": True,
            "confirmed": False,
        }

    async def preview_evm_token_transfer(
        self,
        *,
        token_address: str,
        recipient: str,
        amount_raw: str,
    ) -> dict:
        return {
            "chain": "evm",
            "network": "sepolia",
            "asset_type": "evm-token-transfer",
            "wallet": "evm-wallet-123",
            "from_address": await self.get_address(),
            "recipient": recipient,
            "token_address": token_address,
            "amount_raw": amount_raw,
            "estimated_fee_wei": "45000000000000",
            "source": "fake",
        }

    async def send_evm_token_transfer(
        self,
        *,
        token_address: str,
        recipient: str,
        amount_raw: str,
    ) -> dict:
        preview = await self.preview_evm_token_transfer(
            token_address=token_address,
            recipient=recipient,
            amount_raw=amount_raw,
        )
        return {
            **preview,
            "hash": "0x" + "c" * 64,
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
            external_dependencies=["wdk-evm-wallet"],
        )


async def _main() -> None:
    adapter = OpenClawWalletAdapter(FakeEvmBackend())
    tool_names = {tool.name for tool in adapter.list_tools()}
    assert "transfer_evm_native" in tool_names
    assert "transfer_evm_token" in tool_names
    assert "transfer_btc" not in tool_names
    assert "transfer_sol" not in tool_names

    balance = await adapter.invoke("get_wallet_balance", {})
    assert balance.ok is True
    assert balance.data["balance_wei"] == "1230000000000000000"

    token_balance = await adapter.invoke(
        "get_evm_token_balance",
        {"token_address": "0x2222222222222222222222222222222222222222"},
    )
    assert token_balance.ok is True
    assert token_balance.data["balance_raw"] == "42000000"

    preview = await adapter.invoke(
        "transfer_evm_native",
        {
            "recipient": "0x3333333333333333333333333333333333333333",
            "amount_wei": "10000000000000000",
            "mode": "preview",
            "purpose": "test evm transfer",
        },
    )
    assert preview.ok is True
    assert preview.data["estimated_fee_wei"] == "21000000000000"

    prepared = await adapter.invoke(
        "transfer_evm_token",
        {
            "token_address": "0x2222222222222222222222222222222222222222",
            "recipient": "0x3333333333333333333333333333333333333333",
            "amount_raw": "5000000",
            "mode": "prepare",
            "purpose": "test token transfer",
            "user_intent": True,
        },
    )
    assert prepared.ok is True
    assert prepared.data["execution_plan_only"] is True

    approval = issue_approval_token(
        tool_name="transfer_evm_native",
        network="sepolia",
        summary=preview.data["confirmation_summary"],
        mainnet_confirmed=False,
        issued_by="test",
    )
    executed = await adapter.invoke(
        "transfer_evm_native",
        {
            "recipient": "0x3333333333333333333333333333333333333333",
            "amount_wei": "10000000000000000",
            "mode": "execute",
            "purpose": "test evm transfer",
            "approval_token": approval,
        },
    )
    assert executed.ok is True
    assert executed.data["hash"].startswith("0x")

    class LockedEvmBackend(FakeEvmBackend):
        async def get_balance(self, address: str | None = None) -> dict:
            raise WalletBackendError(
                "Wallet is locked. Unlock it first or provide seedPhrase explicitly.",
                code="wallet_locked",
                details={"source": "wdk-evm-wallet"},
            )

    shaped_error = await OpenClawWalletAdapter(LockedEvmBackend()).invoke("get_wallet_balance", {})
    assert shaped_error.ok is False
    assert shaped_error.error_code == "wallet_locked"
    assert shaped_error.error_details == {"source": "wdk-evm-wallet"}


def main() -> None:
    temp_home = Path("/tmp/openclaw-evm-adapter-smoke")
    if temp_home.exists():
        shutil.rmtree(temp_home)
    install_test_sealed_secrets(
        temp_home,
        boot_key="test-boot-key-for-evm-adapter-smoke",
        master_key="test-master-key-for-evm-adapter-smoke",
        approval_secret="test-approval-secret-for-evm-adapter-smoke",
    )
    asyncio.run(_main())
    print("smoke_openclaw_evm_adapter: ok")


if __name__ == "__main__":
    main()
