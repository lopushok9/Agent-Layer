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
from agent_wallet.providers import lifi  # noqa: E402
from agent_wallet.wallet_layer.base import AgentWalletBackend, WalletBackendError, WalletCapabilities  # noqa: E402


class FakeEvmBackend(AgentWalletBackend):
    name = "wdk_evm_local"
    chain = "evm"
    network = "ethereum"
    sign_only = False

    def with_network(self, network: str) -> "FakeEvmBackend":
        clone = self.__class__()
        clone.network = str(network).strip().lower()
        return clone

    async def get_address(self) -> str | None:
        return "0x1111111111111111111111111111111111111111"

    async def get_balance(self, address: str | None = None) -> dict:
        return {
            "chain": "evm",
            "network": self.network,
            "address": address or await self.get_address(),
            "balance_wei": "1230000000000000000",
            "balance_native": "1.23",
            "asset": "ETH",
            "native_price_usd": "3200",
            "native_value_usd": "3936",
            "tokens": [
                {
                    "token_address": "0x2222222222222222222222222222222222222222",
                    "balance_raw": "42000000",
                    "balance_ui": "42",
                    "token_metadata": {
                        "address": "0x2222222222222222222222222222222222222222",
                        "name": "USD Coin",
                        "symbol": "USDC",
                        "decimals": 6,
                        "verified": False,
                        "source": "fake",
                    },
                    "price_usd": "1",
                    "value_usd": "42",
                }
            ],
            "token_count": 1,
            "total_value_usd": "3978",
            "source": "fake",
        }

    async def get_evm_network_info(self) -> dict:
        return {
            "chain": "evm",
            "network": self.network,
            "configured_network": self.network,
            "service_active_network": self.network,
            "available_networks": ["base", "ethereum"],
            "agent_selectable_networks": ["ethereum", "base"],
            "swap_supported_networks": ["ethereum", "base"],
            "network_profiles": {
                "ethereum": {"chainId": 1, "providerUrl": "https://gateway.example/v1/evm/rpc/ethereum?provider=alchemy"},
                "base": {"chainId": 8453, "providerUrl": "https://gateway.example/v1/evm/rpc/base?provider=alchemy"},
            },
            "selected_profile": {
                "chainId": 1 if self.network == "ethereum" else 8453,
                "providerUrl": f"https://gateway.example/v1/evm/rpc/{self.network}?provider=alchemy",
            },
            "source": "fake",
        }

    async def get_lifi_supported_chains(self) -> dict:
        return {
            "provider": "lifi",
            "chain": "cross-chain",
            "network": "mainnet",
            "chain_count": 3,
            "chains": [
                {"chain_id": "1", "name": "Ethereum"},
                {"chain_id": "8453", "name": "Base"},
                {"chain_id": "1151111081099710", "name": "Solana"},
            ],
            "source": "lifi",
        }

    async def get_lifi_quote(
        self,
        *,
        from_chain: str,
        to_chain: str,
        from_token: str,
        to_token: str,
        amount_in_raw: str,
        from_address: str | None = None,
        to_address: str | None = None,
        slippage: float | int | None = None,
        allow_bridges: list[str] | None = None,
        deny_bridges: list[str] | None = None,
        prefer_bridges: list[str] | None = None,
    ) -> dict:
        return {
            "provider": "lifi",
            "chain": "cross-chain",
            "network": "mainnet",
            "from_chain": from_chain,
            "to_chain": to_chain,
            "from_token": from_token,
            "to_token": to_token,
            "amount_in_raw": amount_in_raw,
            "from_address": from_address or await self.get_address(),
            "to_address": to_address,
            "slippage": slippage,
            "allow_bridges": allow_bridges,
            "deny_bridges": deny_bridges,
            "prefer_bridges": prefer_bridges,
            "tool": "relay",
            "estimate": {"toAmount": "995000", "toAmountMin": "985000"},
            "transaction_request": {"to": "0xrouter", "data": "0x"},
            "quote": {"tool": "relay"},
            "source": "lifi",
        }

    async def get_lifi_transfer_status(
        self,
        *,
        tx_hash: str,
        bridge: str | None = None,
        from_chain: str | None = None,
        to_chain: str | None = None,
    ) -> dict:
        return {
            "provider": "lifi",
            "chain": "cross-chain",
            "network": "mainnet",
            "tx_hash": tx_hash,
            "bridge": bridge,
            "from_chain": from_chain,
            "to_chain": to_chain,
            "status": "DONE",
            "source": "lifi",
        }

    async def get_evm_token_balance(self, token_address: str) -> dict:
        return {
            "chain": "evm",
            "network": self.network,
            "address": await self.get_address(),
            "token_address": token_address,
            "balance_raw": "42000000",
            "balance_ui": "42",
            "token_metadata": {
                "address": token_address,
                "name": "USD Coin",
                "symbol": "USDC",
                "decimals": 6,
                "verified": False,
                "source": "fake",
            },
            "source": "fake",
        }

    async def get_evm_token_metadata(self, token_address: str) -> dict:
        return {
            "chain": "evm",
            "network": self.network,
            "token_address": token_address,
            "token_metadata": {
                "address": token_address,
                "name": "USD Coin",
                "symbol": "USDC",
                "decimals": 6,
                "verified": False,
                "source": "fake",
            },
            "source": "fake",
        }

    async def get_evm_fee_rates(self) -> dict:
        return {
            "chain": "evm",
            "network": self.network,
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
            "network": self.network,
            "tx_hash": tx_hash,
            "found": True,
            "receipt": {"transactionHash": tx_hash, "status": "0x1"},
            "source": "fake",
        }

    async def get_evm_swap_quote(
        self,
        *,
        token_in: str,
        token_out: str,
        amount_in_raw: str,
    ) -> dict:
        return {
            "chain": "evm",
            "network": self.network,
            "address": await self.get_address(),
            "token_in": token_in,
            "token_out": token_out,
            "amount_in_raw": amount_in_raw,
            "amount_in_ui": "1",
            "estimated_output_amount_ui": "0.995",
            "quote": {
                "tokenInAmount": amount_in_raw,
                "tokenOutAmount": "995000",
                "route": "fake-velora-route",
            },
            "protocol": "velora",
            "execution_supported": True,
            "quote_fingerprint": "evm-swap-fingerprint-1",
            "router": "0x4444444444444444444444444444444444444444",
            "estimated_fee_wei": "67000000000000",
            "estimated_swap_fee_wei": "39000000000000",
            "estimated_approval_fee_wei": "28000000000000",
            "slippage_bps": 100,
            "minimum_output_amount_raw": "985050",
            "allowance": {
                "spender": "0x5555555555555555555555555555555555555555",
                "current_allowance_raw": "0",
                "required_allowance_raw": amount_in_raw,
                "approval_required": True,
                "approval_sequence": [
                    {"type": "approve", "amount": amount_in_raw, "estimatedFeeWei": "28000000000000"}
                ],
            },
            "simulation": {
                "ok": None,
                "skipped": True,
                "reason": "allowance_required",
                "message": None,
                "details": None,
            },
            "swap_transaction": {
                "to": "0x4444444444444444444444444444444444444444",
                "value": "0",
                "data_hash": "swap-data-hash-1",
            },
            "token_in_metadata": {
                "address": token_in,
                "name": "USD Coin",
                "symbol": "USDC",
                "decimals": 6,
                "verified": False,
                "source": "fake",
            },
            "token_out_metadata": {
                "address": token_out,
                "name": "Tether USD",
                "symbol": "USDT",
                "decimals": 6,
                "verified": False,
                "source": "fake",
            },
            "source": "fake",
        }

    async def preview_evm_swap(
        self,
        *,
        token_in: str,
        token_out: str,
        amount_in_raw: str,
    ) -> dict:
        return {
            "chain": "evm",
            "network": self.network,
            "asset_type": "evm-swap",
            "asset": "ERC20",
            "wallet": "evm-wallet-123",
            "from_address": await self.get_address(),
            "token_in": token_in,
            "token_out": token_out,
            "input_amount_raw": amount_in_raw,
            "input_amount_ui": "1",
            "estimated_output_amount_raw": "995000",
            "estimated_output_amount_ui": "0.995",
            "estimated_fee_wei": "67000000000000",
            "estimated_swap_fee_wei": "39000000000000",
            "estimated_approval_fee_wei": "28000000000000",
            "slippage_bps": 100,
            "minimum_output_amount_raw": "985050",
            "swap_provider": "velora",
            "execution_supported": True,
            "route_plan": "fake-velora-route",
            "quote_fingerprint": "evm-swap-fingerprint-1",
            "router": "0x4444444444444444444444444444444444444444",
            "allowance": {
                "spender": "0x5555555555555555555555555555555555555555",
                "current_allowance_raw": "0",
                "required_allowance_raw": amount_in_raw,
                "approval_required": True,
                "approval_sequence": [
                    {"type": "approve", "amount": amount_in_raw, "estimatedFeeWei": "28000000000000"}
                ],
            },
            "simulation": {
                "ok": None,
                "skipped": True,
                "reason": "allowance_required",
                "message": None,
                "details": None,
            },
            "swap_transaction": {
                "to": "0x4444444444444444444444444444444444444444",
                "value": "0",
                "data_hash": "swap-data-hash-1",
            },
            "token_in_metadata": {
                "address": token_in,
                "name": "USD Coin",
                "symbol": "USDC",
                "decimals": 6,
                "verified": False,
                "source": "fake",
            },
            "token_out_metadata": {
                "address": token_out,
                "name": "Tether USD",
                "symbol": "USDT",
                "decimals": 6,
                "verified": False,
                "source": "fake",
            },
            "source": "fake",
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
        if expected_quote_fingerprint and expected_quote_fingerprint != "evm-swap-fingerprint-1":
            raise WalletBackendError("swap quote changed", code="swap_quote_changed")
        if minimum_output_amount_raw and minimum_output_amount_raw != "985050":
            raise WalletBackendError("minimum output mismatch", code="swap_quote_changed")
        return {
            "chain": "evm",
            "network": self.network,
            "asset_type": "evm-swap",
            "asset": "ERC20",
            "wallet": "evm-wallet-123",
            "from_address": await self.get_address(),
            "token_in": token_in,
            "token_out": token_out,
            "input_amount_raw": amount_in_raw,
            "input_amount_ui": "1",
            "estimated_output_amount_raw": "995000",
            "estimated_output_amount_ui": "0.995",
            "estimated_fee_wei": "67000000000000",
            "estimated_swap_fee_wei": "39000000000000",
            "estimated_approval_fee_wei": "28000000000000",
            "slippage_bps": 100,
            "minimum_output_amount_raw": "985050",
            "swap_provider": "velora",
            "quote_fingerprint": "evm-swap-fingerprint-1",
            "router": "0x4444444444444444444444444444444444444444",
            "allowance": {
                "spender": "0x5555555555555555555555555555555555555555",
                "current_allowance_raw": amount_in_raw,
                "required_allowance_raw": amount_in_raw,
                "approval_required": False,
                "approval_sequence": [],
            },
            "simulation": {
                "ok": True,
                "skipped": False,
                "reason": None,
                "message": None,
                "details": None,
            },
            "swap_transaction": {
                "to": "0x4444444444444444444444444444444444444444",
                "value": "0",
                "data_hash": "swap-data-hash-1",
            },
            "token_in_metadata": {
                "address": token_in,
                "name": "USD Coin",
                "symbol": "USDC",
                "decimals": 6,
                "verified": False,
                "source": "fake",
            },
            "token_out_metadata": {
                "address": token_out,
                "name": "Tether USD",
                "symbol": "USDT",
                "decimals": 6,
                "verified": False,
                "source": "fake",
            },
            "output_amount_raw": "995000",
            "hash": "0x" + "d" * 64,
            "broadcasted": True,
            "confirmed": False,
            "source": "fake",
        }

    async def preview_evm_lifi_cross_chain_swap(
        self,
        *,
        token_in: str,
        destination_chain: str,
        output_token: str,
        destination_address: str,
        amount_in_raw: str,
        slippage: float | int | None = None,
        allow_bridges: list[str] | None = None,
        deny_bridges: list[str] | None = None,
        prefer_bridges: list[str] | None = None,
    ) -> dict:
        destination_chain_ids = {
            "ethereum": "1",
            "1": "1",
            "base": "8453",
            "8453": "8453",
            "solana": "1151111081099710",
            "1151111081099710": "1151111081099710",
        }
        destination_chain_id = destination_chain_ids.get(destination_chain, destination_chain)
        zero_address = "0x0000000000000000000000000000000000000000"
        token_in_lower = token_in.lower()
        output_token_lower = output_token.lower()
        normalized_token_in = (
            zero_address
            if token_in_lower in {"native", "eth"}
            else token_in_lower
            if token_in_lower.startswith("0x") and len(token_in_lower) == 42
            else token_in
        )
        normalized_output_token = (
            zero_address
            if destination_chain_id in {"1", "8453"} and output_token_lower in {"native", "eth"}
            else output_token_lower
            if destination_chain_id in {"1", "8453"}
            and output_token_lower.startswith("0x")
            and len(output_token_lower) == 42
            else output_token
        )
        return {
            "chain": "evm",
            "network": self.network,
            "asset_type": "evm-lifi-cross-chain-swap",
            "asset": "EVM",
            "wallet": "evm-wallet-123",
            "from_address": await self.get_address(),
            "source_chain": self.network,
            "destination_chain": destination_chain,
            "destination_chain_id": destination_chain_id,
            "token_in": normalized_token_in,
            "output_token": normalized_output_token,
            "destination_address": destination_address,
            "input_amount_raw": amount_in_raw,
            "input_amount_ui": "1",
            "estimated_output_amount_raw": "996830",
            "estimated_output_amount_ui": "0.99683",
            "estimated_fee_wei": "73000000000000",
            "estimated_swap_fee_wei": "45000000000000",
            "estimated_approval_fee_wei": "28000000000000",
            "slippage": 0.01 if slippage is None else slippage,
            "minimum_output_amount_raw": "996000",
            "swap_provider": "lifi",
            "execution_supported": True,
            "route_plan": {"tool": "across", "estimate": {"toAmount": "996830"}},
            "quote_fingerprint": "lifi-evm-fingerprint-1",
            "quote_type": "lifi",
            "quote_id": "lifi-quote-1",
            "tool": "across",
            "router": "0x1231DEB6f5749EF6cE6943a275A1D3E7486F4EaE",
            "allowance": {
                "spender": "0x1231DEB6f5749EF6cE6943a275A1D3E7486F4EaE",
                "current_allowance_raw": "0",
                "required_allowance_raw": amount_in_raw,
                "approval_required": normalized_token_in.lower() != zero_address,
                "approval_sequence": (
                    [{"type": "approve", "amount": amount_in_raw, "estimatedFeeWei": "28000000000000"}]
                    if normalized_token_in.lower() != zero_address
                    else []
                ),
            },
            "simulation": {
                "ok": None if normalized_token_in.lower() != zero_address else True,
                "skipped": normalized_token_in.lower() != zero_address,
                "reason": "allowance_required" if normalized_token_in.lower() != zero_address else None,
                "message": None,
                "details": None,
            },
            "swap_transaction": {
                "to": "0x1231DEB6f5749EF6cE6943a275A1D3E7486F4EaE",
                "value": "0",
                "data_hash": "lifi-evm-data-hash-1",
            },
            "token_in_metadata": {
                "address": normalized_token_in,
                "name": "USD Coin",
                "symbol": "USDC",
                "decimals": 6,
                "verified": False,
                "source": "fake",
            },
            "output_token_metadata": {
                "address": normalized_output_token,
                "name": "USD Coin",
                "symbol": "USDC",
                "decimals": 6,
                "verified": True,
                "source": "fake",
            },
            "source": "fake",
        }

    async def send_evm_lifi_cross_chain_swap(
        self,
        *,
        token_in: str,
        destination_chain: str,
        output_token: str,
        destination_address: str,
        amount_in_raw: str,
        slippage: float | int | None = None,
        allow_bridges: list[str] | None = None,
        deny_bridges: list[str] | None = None,
        prefer_bridges: list[str] | None = None,
        minimum_output_amount_raw: str | None = None,
    ) -> dict:
        if minimum_output_amount_raw and minimum_output_amount_raw != "996000":
            raise WalletBackendError("minimum output mismatch", code="swap_quote_changed")
        preview = await self.preview_evm_lifi_cross_chain_swap(
            token_in=token_in,
            destination_chain=destination_chain,
            output_token=output_token,
            destination_address=destination_address,
            amount_in_raw=amount_in_raw,
            slippage=slippage,
            allow_bridges=allow_bridges,
            deny_bridges=deny_bridges,
            prefer_bridges=prefer_bridges,
        )
        return {
            **preview,
            "output_amount_raw": "996830",
            "hash": "0x" + "f" * 64,
            "broadcasted": True,
            "confirmed": False,
        }

    async def preview_evm_native_transfer(
        self,
        *,
        recipient: str,
        amount_wei: str,
    ) -> dict:
        return {
            "chain": "evm",
            "network": self.network,
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
            "network": self.network,
            "asset_type": "evm-token-transfer",
            "wallet": "evm-wallet-123",
            "from_address": await self.get_address(),
            "recipient": recipient,
            "token_address": token_address,
            "amount_raw": amount_raw,
            "amount_ui": "5",
            "estimated_fee_wei": "45000000000000",
            "token_metadata": {
                "address": token_address,
                "name": "USD Coin",
                "symbol": "USDC",
                "decimals": 6,
                "verified": False,
                "source": "fake",
            },
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
    assert "get_lifi_supported_chains" in tool_names
    assert "get_lifi_quote" in tool_names
    assert "get_lifi_transfer_status" in tool_names
    assert "swap_evm_lifi_cross_chain_tokens" in tool_names
    assert "get_evm_network" in tool_names
    assert "get_evm_token_metadata" in tool_names
    assert "get_evm_swap_quote" in tool_names
    assert "swap_evm_tokens" in tool_names
    assert "transfer_evm_native" in tool_names
    assert "transfer_evm_token" in tool_names
    assert "transfer_btc" not in tool_names
    assert "transfer_sol" not in tool_names
    lifi_swap_tool = next(tool for tool in adapter.list_tools() if tool.name == "swap_evm_lifi_cross_chain_tokens")
    lifi_destination_enum = lifi_swap_tool.input_schema["properties"]["destination_chain"]["enum"]
    assert "ethereum" in lifi_destination_enum
    assert "base" in lifi_destination_enum
    assert "solana" in lifi_destination_enum
    assert (
        lifi.normalize_token_address("0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913", chain_id="8453")
        == "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913"
    )

    balance = await adapter.invoke("get_wallet_balance", {})
    assert balance.ok is True
    assert balance.data["balance_wei"] == "1230000000000000000"
    assert balance.data["token_count"] == 1
    assert balance.data["total_value_usd"] == "3978"

    base_balance = await adapter.invoke("get_wallet_balance", {"network": "base"})
    assert base_balance.ok is True
    assert base_balance.data["network"] == "base"

    network_info = await adapter.invoke("get_evm_network", {"network": "base"})
    assert network_info.ok is True
    assert network_info.data["configured_network"] == "base"
    assert "ethereum" in network_info.data["agent_selectable_networks"]
    assert "base" in network_info.data["agent_selectable_networks"]

    token_balance = await adapter.invoke(
        "get_evm_token_balance",
        {"token_address": "0x2222222222222222222222222222222222222222", "network": "base"},
    )
    assert token_balance.ok is True
    assert token_balance.data["balance_raw"] == "42000000"
    assert token_balance.data["token_metadata"]["symbol"] == "USDC"
    assert token_balance.data["network"] == "base"

    token_metadata = await adapter.invoke(
        "get_evm_token_metadata",
        {"token_address": "0x2222222222222222222222222222222222222222", "network": "base"},
    )
    assert token_metadata.ok is True
    assert token_metadata.data["token_metadata"]["decimals"] == 6
    assert token_metadata.data["network"] == "base"

    lifi_chains = await adapter.invoke("get_lifi_supported_chains", {})
    assert lifi_chains.ok is True
    assert lifi_chains.data["chain_count"] == 3

    lifi_quote = await adapter.invoke(
        "get_lifi_quote",
        {
            "from_chain": "base",
            "to_chain": "solana",
            "from_token": "native",
            "to_token": "native",
            "amount_in_raw": "1000000",
            "to_address": "FakeSolanaAddress111111111111111111111111111",
            "slippage": 0.01,
        },
    )
    assert lifi_quote.ok is True
    assert lifi_quote.data["tool"] == "relay"

    lifi_status = await adapter.invoke(
        "get_lifi_transfer_status",
        {"tx_hash": "0xsourcehash", "from_chain": "base", "to_chain": "solana"},
    )
    assert lifi_status.ok is True
    assert lifi_status.data["status"] == "DONE"

    swap_quote = await adapter.invoke(
        "get_evm_swap_quote",
        {
            "token_in": "0x2222222222222222222222222222222222222222",
            "token_out": "0x3333333333333333333333333333333333333333",
            "amount_in_raw": "1000000",
            "network": "base",
        },
    )
    assert swap_quote.ok is True
    assert swap_quote.data["protocol"] == "velora"
    assert swap_quote.data["network"] == "base"
    assert swap_quote.data["execution_supported"] is True
    assert swap_quote.data["quote_fingerprint"] == "evm-swap-fingerprint-1"
    assert swap_quote.data["allowance"]["approval_required"] is True
    assert swap_quote.data["token_in_metadata"]["symbol"] == "USDC"
    assert swap_quote.data["token_out_metadata"]["symbol"] == "USDT"

    swap_preview = await adapter.invoke(
        "swap_evm_tokens",
        {
            "token_in": "0x2222222222222222222222222222222222222222",
            "token_out": "0x3333333333333333333333333333333333333333",
            "amount_in_raw": "1000000",
            "mode": "preview",
            "purpose": "test evm swap",
        },
    )
    assert swap_preview.ok is True
    assert swap_preview.data["asset_type"] == "evm-swap"
    assert swap_preview.data["estimated_output_amount_raw"] == "995000"
    assert swap_preview.data["estimated_output_amount_ui"] == "0.995"
    assert swap_preview.data["quote_fingerprint"] == "evm-swap-fingerprint-1"
    assert swap_preview.data["estimated_approval_fee_wei"] == "28000000000000"
    assert swap_preview.data["swap_transaction"]["data_hash"] == "swap-data-hash-1"
    assert swap_preview.data["minimum_output_amount_raw"] == "985050"
    assert swap_preview.data["slippage_bps"] == 100

    lifi_cross_chain_preview = await adapter.invoke(
        "swap_evm_lifi_cross_chain_tokens",
        {
            "token_in": "0x2222222222222222222222222222222222222222",
            "destination_chain": "solana",
            "output_token": "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
            "destination_address": "ENsytooJVSZyNHbxvueUeX8Am8gcNqPivVVE8USCBiy5",
            "amount_in_raw": "1000000",
            "slippage": 0.01,
            "mode": "preview",
            "purpose": "test evm lifi cross-chain swap",
        },
    )
    assert lifi_cross_chain_preview.ok is True
    assert lifi_cross_chain_preview.data["asset_type"] == "evm-lifi-cross-chain-swap"
    assert lifi_cross_chain_preview.data["swap_provider"] == "lifi"
    assert lifi_cross_chain_preview.data["tool"] == "across"
    assert lifi_cross_chain_preview.data["minimum_output_amount_raw"] == "996000"

    lifi_evm_to_evm_preview = await adapter.invoke(
        "swap_evm_lifi_cross_chain_tokens",
        {
            "token_in": "0x0000000000000000000000000000000000000000",
            "destination_chain": "base",
            "output_token": "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913",
            "destination_address": "0x3333333333333333333333333333333333333333",
            "amount_in_raw": "1000000000000000",
            "slippage": 0.01,
            "mode": "preview",
            "purpose": "test evm lifi evm-to-evm cross-chain swap",
        },
    )
    assert lifi_evm_to_evm_preview.ok is True
    assert lifi_evm_to_evm_preview.data["destination_chain"] == "base"
    assert lifi_evm_to_evm_preview.data["destination_chain_id"] == "8453"
    assert (
        lifi_evm_to_evm_preview.data["confirmation_summary"]["output_token"]
        == "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913"
    )

    lifi_native_alias_preview = await adapter.invoke(
        "swap_evm_lifi_cross_chain_tokens",
        {
            "token_in": "eth",
            "destination_chain": "base",
            "output_token": "native",
            "destination_address": "0x3333333333333333333333333333333333333333",
            "amount_in_raw": "1000000000000000",
            "slippage": 0.01,
            "mode": "preview",
            "purpose": "test evm lifi native alias approval binding",
        },
    )
    assert lifi_native_alias_preview.ok is True
    assert (
        lifi_native_alias_preview.data["confirmation_summary"]["token_in"]
        == "0x0000000000000000000000000000000000000000"
    )
    assert (
        lifi_native_alias_preview.data["confirmation_summary"]["output_token"]
        == "0x0000000000000000000000000000000000000000"
    )
    lifi_native_alias_approval = issue_approval_token(
        tool_name="swap_evm_lifi_cross_chain_tokens",
        network="ethereum",
        summary=lifi_native_alias_preview.data["confirmation_summary"],
        mainnet_confirmed=True,
        issued_by="test",
    )
    lifi_native_alias_execute = await adapter.invoke(
        "swap_evm_lifi_cross_chain_tokens",
        {
            "token_in": "eth",
            "destination_chain": "8453",
            "output_token": "native",
            "destination_address": "0x3333333333333333333333333333333333333333",
            "amount_in_raw": "1000000000000000",
            "slippage": 0.01,
            "mode": "execute",
            "purpose": "test evm lifi native alias approval binding",
            "approval_token": lifi_native_alias_approval,
        },
    )
    assert lifi_native_alias_execute.ok is True
    assert lifi_native_alias_execute.data["hash"].startswith("0x")

    lifi_cross_chain_prepare = await adapter.invoke(
        "swap_evm_lifi_cross_chain_tokens",
        {
            "token_in": "0x2222222222222222222222222222222222222222",
            "destination_chain": "solana",
            "output_token": "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
            "destination_address": "ENsytooJVSZyNHbxvueUeX8Am8gcNqPivVVE8USCBiy5",
            "amount_in_raw": "1000000",
            "slippage": 0.01,
            "mode": "prepare",
            "purpose": "test evm lifi cross-chain swap",
            "user_intent": True,
        },
    )
    assert lifi_cross_chain_prepare.ok is True
    assert lifi_cross_chain_prepare.data["execution_plan_only"] is True

    lifi_cross_chain_approval = issue_approval_token(
        tool_name="swap_evm_lifi_cross_chain_tokens",
        network="ethereum",
        summary=lifi_cross_chain_preview.data["confirmation_summary"],
        mainnet_confirmed=True,
        issued_by="test",
    )
    lifi_cross_chain_execute = await adapter.invoke(
        "swap_evm_lifi_cross_chain_tokens",
        {
            "token_in": "0x2222222222222222222222222222222222222222",
            "destination_chain": "solana",
            "output_token": "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
            "destination_address": "ENsytooJVSZyNHbxvueUeX8Am8gcNqPivVVE8USCBiy5",
            "amount_in_raw": "1000000",
            "slippage": 0.01,
            "mode": "execute",
            "purpose": "test evm lifi cross-chain swap",
            "approval_token": lifi_cross_chain_approval,
        },
    )
    assert lifi_cross_chain_execute.ok is True
    assert lifi_cross_chain_execute.data["hash"].startswith("0x")
    assert lifi_cross_chain_execute.data["minimum_output_amount_raw"] == "996000"

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
    assert prepared.data["token_metadata"]["decimals"] == 6

    swap_approval = issue_approval_token(
        tool_name="swap_evm_tokens",
        network="ethereum",
        summary=swap_preview.data["confirmation_summary"],
        mainnet_confirmed=True,
        issued_by="test",
    )
    swap_executed = await adapter.invoke(
        "swap_evm_tokens",
        {
            "token_in": "0x2222222222222222222222222222222222222222",
            "token_out": "0x3333333333333333333333333333333333333333",
            "amount_in_raw": "1000000",
            "mode": "execute",
            "purpose": "test evm swap",
            "approval_token": swap_approval,
        },
    )
    assert swap_executed.ok is True
    assert swap_executed.data["hash"].startswith("0x")
    assert swap_executed.data["allowance"]["approval_required"] is False
    assert swap_executed.data["simulation"]["ok"] is True
    assert swap_preview.data["confirmation_summary"]["quote_fingerprint"] == "evm-swap-fingerprint-1"
    assert swap_preview.data["confirmation_summary"]["minimum_output_amount_raw"] == "985050"
    assert swap_preview.data["confirmation_summary"]["slippage_bps"] == 100

    class NoRepreviewEvmBackend(FakeEvmBackend):
        def __init__(self) -> None:
            self.preview_calls = 0

        async def preview_evm_swap(
            self,
            *,
            token_in: str,
            token_out: str,
            amount_in_raw: str,
        ) -> dict:
            self.preview_calls += 1
            if self.preview_calls > 1:
                raise WalletBackendError("execute should not request a second preview")
            return await super().preview_evm_swap(
                token_in=token_in,
                token_out=token_out,
                amount_in_raw=amount_in_raw,
            )

    no_repreview_backend = NoRepreviewEvmBackend()
    no_repreview_adapter = OpenClawWalletAdapter(no_repreview_backend)
    no_repreview_preview = await no_repreview_adapter.invoke(
        "swap_evm_tokens",
        {
            "token_in": "0x2222222222222222222222222222222222222222",
            "token_out": "0x3333333333333333333333333333333333333333",
            "amount_in_raw": "1000000",
            "mode": "preview",
            "purpose": "test evm swap",
        },
    )
    no_repreview_approval = issue_approval_token(
        tool_name="swap_evm_tokens",
        network="ethereum",
        summary=no_repreview_preview.data["confirmation_summary"],
        mainnet_confirmed=True,
        issued_by="test",
    )
    no_repreview_execute = await no_repreview_adapter.invoke(
        "swap_evm_tokens",
        {
            "token_in": "0x2222222222222222222222222222222222222222",
            "token_out": "0x3333333333333333333333333333333333333333",
            "amount_in_raw": "1000000",
            "mode": "execute",
            "purpose": "test evm swap",
            "approval_token": no_repreview_approval,
        },
    )
    assert no_repreview_execute.ok is True
    assert no_repreview_backend.preview_calls == 1

    class QuoteChangedEvmBackend(FakeEvmBackend):
        async def send_evm_swap(
            self,
            *,
            token_in: str,
            token_out: str,
            amount_in_raw: str,
            expected_quote_fingerprint: str | None = None,
            minimum_output_amount_raw: str | None = None,
        ) -> dict:
            raise WalletBackendError(
                "Swap quote changed since preview. Generate a new preview and approval before execute.",
                code="swap_quote_changed",
                details={"source": "wdk-evm-wallet"},
            )

    quote_changed_adapter = OpenClawWalletAdapter(QuoteChangedEvmBackend())
    quote_changed_preview = await quote_changed_adapter.invoke(
        "swap_evm_tokens",
        {
            "token_in": "0x2222222222222222222222222222222222222222",
            "token_out": "0x3333333333333333333333333333333333333333",
            "amount_in_raw": "1000000",
            "mode": "preview",
            "purpose": "test evm swap",
        },
    )
    quote_changed_approval = issue_approval_token(
        tool_name="swap_evm_tokens",
        network="ethereum",
        summary=quote_changed_preview.data["confirmation_summary"],
        mainnet_confirmed=True,
        issued_by="test",
    )
    quote_changed = await quote_changed_adapter.invoke(
        "swap_evm_tokens",
        {
            "token_in": "0x2222222222222222222222222222222222222222",
            "token_out": "0x3333333333333333333333333333333333333333",
            "amount_in_raw": "1000000",
            "mode": "execute",
            "purpose": "test evm swap",
            "approval_token": quote_changed_approval,
        },
    )
    assert quote_changed.ok is False
    assert quote_changed.error_code == "swap_quote_changed"

    class CleanupFailedEvmBackend(FakeEvmBackend):
        async def send_evm_swap(
            self,
            *,
            token_in: str,
            token_out: str,
            amount_in_raw: str,
            expected_quote_fingerprint: str | None = None,
            minimum_output_amount_raw: str | None = None,
        ) -> dict:
            raise WalletBackendError(
                "Swap failed after approval and automatic allowance restore did not complete.",
                code="swap_cleanup_failed",
                details={"source": "wdk-evm-wallet", "cleanup": {"attempted": True, "restored": False}},
            )

    cleanup_failed_adapter = OpenClawWalletAdapter(CleanupFailedEvmBackend())
    cleanup_failed_preview = await cleanup_failed_adapter.invoke(
        "swap_evm_tokens",
        {
            "token_in": "0x2222222222222222222222222222222222222222",
            "token_out": "0x3333333333333333333333333333333333333333",
            "amount_in_raw": "1000000",
            "mode": "preview",
            "purpose": "test evm swap",
        },
    )
    cleanup_failed_approval = issue_approval_token(
        tool_name="swap_evm_tokens",
        network="ethereum",
        summary=cleanup_failed_preview.data["confirmation_summary"],
        mainnet_confirmed=True,
        issued_by="test",
    )
    cleanup_failed = await cleanup_failed_adapter.invoke(
        "swap_evm_tokens",
        {
            "token_in": "0x2222222222222222222222222222222222222222",
            "token_out": "0x3333333333333333333333333333333333333333",
            "amount_in_raw": "1000000",
            "mode": "execute",
            "purpose": "test evm swap",
            "approval_token": cleanup_failed_approval,
        },
    )
    assert cleanup_failed.ok is False
    assert cleanup_failed.error_code == "swap_cleanup_failed"

    approval = issue_approval_token(
        tool_name="transfer_evm_native",
        network="ethereum",
        summary=preview.data["confirmation_summary"],
        mainnet_confirmed=True,
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
