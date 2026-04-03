"""Local EVM backend backed by the wdk-evm-wallet service."""

from __future__ import annotations

from typing import Any

from agent_wallet.providers.wdk_evm_local import WdkEvmLocalClient
from agent_wallet.wallet_layer.base import AgentWalletBackend, WalletBackendError, WalletCapabilities


def _normalize_evm_network(value: str | None) -> str:
    network = str(value or "").strip().lower()
    aliases = {
        "mainnet": "ethereum",
        "eth": "ethereum",
        "eth-mainnet": "ethereum",
        "base-mainnet": "base",
        "base_sepolia": "base-sepolia",
    }
    network = aliases.get(network, network)
    if network not in {"ethereum", "sepolia", "base", "base-sepolia"}:
        return "ethereum"
    return network


def _extract_fee_wei(payload: dict[str, Any]) -> str | None:
    for key in ("fee", "maxFee", "totalFee", "gasCost", "cost"):
        value = payload.get(key)
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return None


def _normalize_swap_route(quote: dict[str, Any]) -> Any:
    for key in ("routePlan", "route", "priceRoute"):
        value = quote.get(key)
        if value is not None:
            return value
    return None


def _normalize_token_metadata(payload: Any, token_address: str | None = None) -> dict[str, Any] | None:
    if not isinstance(payload, dict):
        return None
    address = str(payload.get("address") or token_address or "").strip()
    name = payload.get("name")
    symbol = payload.get("symbol")
    decimals = payload.get("decimals")
    normalized: dict[str, Any] = {
        "address": address,
        "name": str(name) if name is not None else None,
        "symbol": str(symbol) if symbol is not None else None,
        "decimals": int(decimals) if decimals is not None else None,
        "verified": bool(payload.get("verified")),
        "source": str(payload.get("source") or "erc20-rpc"),
    }
    return normalized


class WdkEvmLocalWalletBackend(AgentWalletBackend):
    """EVM backend that delegates signing and execution to a local WDK service."""

    name = "wdk_evm_local"

    def __init__(
        self,
        *,
        service_url: str,
        wallet_id: str,
        network: str,
        account_index: int = 0,
        sign_only: bool = False,
        address: str | None = None,
    ):
        self.client = WdkEvmLocalClient(service_url)
        self.wallet_id = str(wallet_id or "").strip()
        if not self.wallet_id:
            raise WalletBackendError("WDK EVM wallet id is not configured.")
        self.network = _normalize_evm_network(network)
        self.account_index = int(account_index)
        self.sign_only = bool(sign_only)
        self.address = address.strip() if isinstance(address, str) and address.strip() else None
        self.chain = "evm"
        self.custody_model = "local_service_vault"

    async def get_address(self) -> str | None:
        if self.address:
            return self.address
        data = await self.client.post(
            "/v1/evm/address/resolve",
            {
                "walletId": self.wallet_id,
                "accountIndex": self.account_index,
                "network": self.network,
            },
        )
        address = str(data.get("address") or "").strip()
        if not address:
            raise WalletBackendError("wdk-evm-wallet did not return an address.")
        self.address = address
        return address

    async def get_balance(self, address: str | None = None) -> dict[str, Any]:
        resolved_address = await self.get_address()
        if address is not None and address.strip() and address.strip() != resolved_address:
            raise WalletBackendError(
                "wdk_evm_local only supports the configured default EVM account address."
            )
        data = await self.client.post(
            "/v1/evm/balance/get",
            {
                "walletId": self.wallet_id,
                "accountIndex": self.account_index,
                "network": self.network,
            },
        )
        return {
            "chain": self.chain,
            "network": self.network,
            "address": str(data.get("address") or resolved_address or ""),
            "balance_wei": str(data.get("balance") or "0"),
            "balance_native": str(data.get("balanceFormatted") or "0"),
            "asset": str(data.get("nativeSymbol") or "ETH"),
            "chain_id": int(data.get("chainId") or 0),
            "source": "wdk-evm-wallet",
        }

    async def get_evm_token_balance(self, token_address: str) -> dict[str, Any]:
        data = await self.client.post(
            "/v1/evm/token-balance/get",
            {
                "walletId": self.wallet_id,
                "accountIndex": self.account_index,
                "network": self.network,
                "tokenAddress": token_address,
            },
        )
        return {
            "chain": self.chain,
            "network": self.network,
            "address": str(data.get("address") or await self.get_address() or ""),
            "token_address": str(data.get("tokenAddress") or token_address),
            "balance_raw": str(data.get("balance") or "0"),
            "balance_ui": str(data.get("balanceFormatted")) if data.get("balanceFormatted") is not None else None,
            "token_metadata": _normalize_token_metadata(
                data.get("tokenMetadata"),
                str(data.get("tokenAddress") or token_address),
            ),
            "chain_id": int(data.get("chainId") or 0),
            "source": "wdk-evm-wallet",
        }

    async def get_evm_token_metadata(self, token_address: str) -> dict[str, Any]:
        data = await self.client.post(
            "/v1/evm/token-metadata/get",
            {
                "network": self.network,
                "tokenAddress": token_address,
            },
        )
        resolved = _normalize_token_metadata(
            data.get("tokenMetadata"),
            str(data.get("tokenAddress") or token_address),
        )
        return {
            "chain": self.chain,
            "network": self.network,
            "token_address": str(data.get("tokenAddress") or token_address),
            "token_metadata": resolved,
            "chain_id": int(data.get("chainId") or 0),
            "source": "wdk-evm-wallet",
        }

    async def get_evm_fee_rates(self) -> dict[str, Any]:
        data = await self.client.post(
            "/v1/evm/fee-rates/get",
            {"network": self.network},
        )
        return {
            "chain": self.chain,
            "network": self.network,
            "chain_id": int(data.get("chainId") or 0),
            "gas_price_wei": str(data.get("gasPrice") or "0"),
            "fee_rates": data.get("feeRates") or {},
            "source": "wdk-evm-wallet",
        }

    async def get_evm_transaction_receipt(self, tx_hash: str) -> dict[str, Any]:
        data = await self.client.post(
            "/v1/evm/transaction/receipt/get",
            {
                "network": self.network,
                "txHash": tx_hash,
            },
        )
        return {
            "chain": self.chain,
            "network": self.network,
            "chain_id": int(data.get("chainId") or 0),
            "tx_hash": tx_hash,
            "found": bool(data.get("found")),
            "receipt": data.get("receipt"),
            "source": "wdk-evm-wallet",
        }

    async def get_evm_swap_quote(
        self,
        *,
        token_in: str,
        token_out: str,
        amount_in_raw: str,
    ) -> dict[str, Any]:
        data = await self.client.post(
            "/v1/evm/swap/quote",
            {
                "walletId": self.wallet_id,
                "accountIndex": self.account_index,
                "network": self.network,
                "tokenIn": token_in,
                "tokenOut": token_out,
                "tokenInAmount": amount_in_raw,
            },
        )
        return {
            "chain": self.chain,
            "network": self.network,
            "address": str(data.get("address") or await self.get_address() or ""),
            "token_in": str((data.get("swapRequest") or {}).get("tokenIn") or token_in),
            "token_out": str((data.get("swapRequest") or {}).get("tokenOut") or token_out),
            "amount_in_raw": str((data.get("swapRequest") or {}).get("tokenInAmount") or amount_in_raw),
            "amount_in_ui": str(data.get("inputAmountFormatted")) if data.get("inputAmountFormatted") is not None else None,
            "estimated_output_amount_ui": (
                str(data.get("outputAmountFormatted")) if data.get("outputAmountFormatted") is not None else None
            ),
            "quote": dict(data.get("quote") or {}),
            "protocol": str(data.get("protocol") or "velora"),
            "execution_supported": bool(data.get("executionSupported")) and not self.sign_only,
            "token_in_metadata": _normalize_token_metadata(
                data.get("tokenInMetadata"),
                str((data.get("swapRequest") or {}).get("tokenIn") or token_in),
            ),
            "token_out_metadata": _normalize_token_metadata(
                data.get("tokenOutMetadata"),
                str((data.get("swapRequest") or {}).get("tokenOut") or token_out),
            ),
            "chain_id": int(data.get("chainId") or 0),
            "source": "wdk-evm-wallet",
        }

    async def preview_evm_swap(
        self,
        *,
        token_in: str,
        token_out: str,
        amount_in_raw: str,
    ) -> dict[str, Any]:
        data = await self.client.post(
            "/v1/evm/swap/quote",
            {
                "walletId": self.wallet_id,
                "accountIndex": self.account_index,
                "network": self.network,
                "tokenIn": token_in,
                "tokenOut": token_out,
                "tokenInAmount": amount_in_raw,
            },
        )
        quote = dict(data.get("quote") or {})
        return {
            "chain": self.chain,
            "network": self.network,
            "asset_type": "evm-swap",
            "asset": "ERC20",
            "wallet": self.wallet_id,
            "from_address": await self.get_address(),
            "token_in": str((data.get("swapRequest") or {}).get("tokenIn") or token_in),
            "token_out": str((data.get("swapRequest") or {}).get("tokenOut") or token_out),
            "input_amount_raw": str((data.get("swapRequest") or {}).get("tokenInAmount") or amount_in_raw),
            "input_amount_ui": str(data.get("inputAmountFormatted")) if data.get("inputAmountFormatted") is not None else None,
            "estimated_output_amount_raw": str(quote.get("tokenOutAmount") or "0"),
            "estimated_output_amount_ui": (
                str(data.get("outputAmountFormatted")) if data.get("outputAmountFormatted") is not None else None
            ),
            "estimated_fee_wei": _extract_fee_wei(quote),
            "swap_provider": str(data.get("protocol") or "velora"),
            "execution_supported": bool(data.get("executionSupported")) and not self.sign_only,
            "route_plan": _normalize_swap_route(quote),
            "token_in_metadata": _normalize_token_metadata(
                data.get("tokenInMetadata"),
                str((data.get("swapRequest") or {}).get("tokenIn") or token_in),
            ),
            "token_out_metadata": _normalize_token_metadata(
                data.get("tokenOutMetadata"),
                str((data.get("swapRequest") or {}).get("tokenOut") or token_out),
            ),
            "quote": quote,
            "chain_id": int(data.get("chainId") or 0),
            "source": "wdk-evm-wallet",
        }

    async def send_evm_swap(
        self,
        *,
        token_in: str,
        token_out: str,
        amount_in_raw: str,
    ) -> dict[str, Any]:
        if self.sign_only:
            raise WalletBackendError("wdk_evm_local is configured as sign_only.")
        data = await self.client.post(
            "/v1/evm/swap/send",
            {
                "walletId": self.wallet_id,
                "accountIndex": self.account_index,
                "network": self.network,
                "tokenIn": token_in,
                "tokenOut": token_out,
                "tokenInAmount": amount_in_raw,
            },
        )
        result = dict(data.get("result") or {})
        return {
            "chain": self.chain,
            "network": self.network,
            "asset_type": "evm-swap",
            "asset": "ERC20",
            "wallet": self.wallet_id,
            "from_address": await self.get_address(),
            "token_in": str((data.get("swapRequest") or {}).get("tokenIn") or token_in),
            "token_out": str((data.get("swapRequest") or {}).get("tokenOut") or token_out),
            "input_amount_raw": str((data.get("swapRequest") or {}).get("tokenInAmount") or amount_in_raw),
            "input_amount_ui": str(data.get("inputAmountFormatted")) if data.get("inputAmountFormatted") is not None else None,
            "output_amount_raw": str(result.get("tokenOutAmount") or "0"),
            "estimated_output_amount_raw": str(result.get("tokenOutAmount") or "0"),
            "estimated_output_amount_ui": (
                str(data.get("outputAmountFormatted")) if data.get("outputAmountFormatted") is not None else None
            ),
            "estimated_fee_wei": _extract_fee_wei(result),
            "swap_provider": str(data.get("protocol") or "velora"),
            "token_in_metadata": _normalize_token_metadata(
                data.get("tokenInMetadata"),
                str((data.get("swapRequest") or {}).get("tokenIn") or token_in),
            ),
            "token_out_metadata": _normalize_token_metadata(
                data.get("tokenOutMetadata"),
                str((data.get("swapRequest") or {}).get("tokenOut") or token_out),
            ),
            "hash": result.get("hash"),
            "approve_hash": result.get("approveHash"),
            "reset_allowance_hash": result.get("resetAllowanceHash"),
            "result": result,
            "chain_id": int(data.get("chainId") or 0),
            "broadcasted": True,
            "confirmed": False,
            "source": "wdk-evm-wallet",
        }

    async def preview_evm_native_transfer(
        self,
        *,
        recipient: str,
        amount_wei: str,
    ) -> dict[str, Any]:
        data = await self.client.post(
            "/v1/evm/transfer/quote",
            {
                "walletId": self.wallet_id,
                "accountIndex": self.account_index,
                "network": self.network,
                "to": recipient,
                "value": amount_wei,
            },
        )
        quote = dict(data.get("quote") or {})
        return {
            "chain": self.chain,
            "network": self.network,
            "asset_type": "evm-native-transfer",
            "asset": "ETH",
            "wallet": self.wallet_id,
            "from_address": await self.get_address(),
            "recipient": recipient,
            "amount_wei": str(amount_wei),
            "estimated_fee_wei": _extract_fee_wei(quote),
            "quote": quote,
            "chain_id": int(data.get("chainId") or 0),
            "source": "wdk-evm-wallet",
        }

    async def send_evm_native_transfer(
        self,
        *,
        recipient: str,
        amount_wei: str,
    ) -> dict[str, Any]:
        if self.sign_only:
            raise WalletBackendError("wdk_evm_local is configured as sign_only.")
        data = await self.client.post(
            "/v1/evm/transfer/send",
            {
                "walletId": self.wallet_id,
                "accountIndex": self.account_index,
                "network": self.network,
                "to": recipient,
                "value": amount_wei,
            },
        )
        result = dict(data.get("result") or {})
        return {
            "chain": self.chain,
            "network": self.network,
            "asset_type": "evm-native-transfer",
            "asset": "ETH",
            "wallet": self.wallet_id,
            "from_address": await self.get_address(),
            "recipient": recipient,
            "amount_wei": str(amount_wei),
            "estimated_fee_wei": _extract_fee_wei(result),
            "hash": result.get("hash"),
            "result": result,
            "chain_id": int(data.get("chainId") or 0),
            "broadcasted": True,
            "confirmed": False,
            "source": "wdk-evm-wallet",
        }

    async def preview_evm_token_transfer(
        self,
        *,
        token_address: str,
        recipient: str,
        amount_raw: str,
    ) -> dict[str, Any]:
        data = await self.client.post(
            "/v1/evm/token-transfer/quote",
            {
                "walletId": self.wallet_id,
                "accountIndex": self.account_index,
                "network": self.network,
                "tokenAddress": token_address,
                "recipient": recipient,
                "amount": amount_raw,
            },
        )
        quote = dict(data.get("quote") or {})
        return {
            "chain": self.chain,
            "network": self.network,
            "asset_type": "evm-token-transfer",
            "wallet": self.wallet_id,
            "from_address": await self.get_address(),
            "recipient": recipient,
            "token_address": token_address,
            "amount_raw": str(amount_raw),
            "amount_ui": str(data.get("amountFormatted")) if data.get("amountFormatted") is not None else None,
            "estimated_fee_wei": _extract_fee_wei(quote),
            "token_metadata": _normalize_token_metadata(data.get("tokenMetadata"), token_address),
            "quote": quote,
            "chain_id": int(data.get("chainId") or 0),
            "source": "wdk-evm-wallet",
        }

    async def send_evm_token_transfer(
        self,
        *,
        token_address: str,
        recipient: str,
        amount_raw: str,
    ) -> dict[str, Any]:
        if self.sign_only:
            raise WalletBackendError("wdk_evm_local is configured as sign_only.")
        data = await self.client.post(
            "/v1/evm/token-transfer/send",
            {
                "walletId": self.wallet_id,
                "accountIndex": self.account_index,
                "network": self.network,
                "tokenAddress": token_address,
                "recipient": recipient,
                "amount": amount_raw,
            },
        )
        result = dict(data.get("result") or {})
        return {
            "chain": self.chain,
            "network": self.network,
            "asset_type": "evm-token-transfer",
            "wallet": self.wallet_id,
            "from_address": await self.get_address(),
            "recipient": recipient,
            "token_address": token_address,
            "amount_raw": str(amount_raw),
            "amount_ui": str(data.get("amountFormatted")) if data.get("amountFormatted") is not None else None,
            "estimated_fee_wei": _extract_fee_wei(result),
            "token_metadata": _normalize_token_metadata(data.get("tokenMetadata"), token_address),
            "hash": result.get("hash"),
            "result": result,
            "chain_id": int(data.get("chainId") or 0),
            "broadcasted": True,
            "confirmed": False,
            "source": "wdk-evm-wallet",
        }

    def get_capabilities(self) -> WalletCapabilities:
        return WalletCapabilities(
            backend=self.name,
            chain=self.chain,
            custody_model=self.custody_model,
            sign_only=self.sign_only,
            has_signer=True,
            can_get_address=True,
            can_get_balance=True,
            can_sign_message=False,
            can_sign_transaction=not self.sign_only,
            can_send_transaction=not self.sign_only,
            external_dependencies=["wdk-evm-wallet", "evm-rpc"],
        )
