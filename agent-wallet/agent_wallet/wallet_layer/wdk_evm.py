"""Local EVM backend backed by the wdk-evm-wallet service."""

from __future__ import annotations

from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from typing import Any

from agent_wallet.providers.evm_portfolio import build_portfolio_snapshot
from agent_wallet.providers import mayan
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


def _normalize_swap_allowance(payload: Any) -> dict[str, Any] | None:
    if not isinstance(payload, dict):
        return None
    return {
        "spender": str(payload.get("spender") or "").strip() or None,
        "current_allowance_raw": str(payload.get("currentAllowance") or "0"),
        "required_allowance_raw": str(payload.get("requiredAllowance") or "0"),
        "approval_required": bool(payload.get("approvalRequired")),
        "approval_sequence": list(payload.get("approvalSequence") or []),
    }


def _normalize_swap_simulation(payload: Any) -> dict[str, Any] | None:
    if not isinstance(payload, dict):
        return None
    return {
        "ok": payload.get("ok"),
        "skipped": bool(payload.get("skipped")),
        "reason": str(payload.get("reason") or "").strip() or None,
        "message": str(payload.get("message") or "").strip() or None,
        "details": dict(payload.get("details") or {}) if isinstance(payload.get("details"), dict) else None,
    }


def _sanitize_provider_url(value: Any) -> str | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        split = urlsplit(raw)
    except Exception:
        return raw
    query = []
    for key, item in parse_qsl(split.query, keep_blank_values=True):
        if key.lower() in {"token", "apikey", "api_key"}:
            query.append((key, "***"))
        else:
            query.append((key, item))
    return urlunsplit((split.scheme, split.netloc, split.path, urlencode(query), split.fragment))


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

    def with_network(self, network: str) -> "WdkEvmLocalWalletBackend":
        return WdkEvmLocalWalletBackend(
            service_url=self.client.base_url,
            wallet_id=self.wallet_id,
            network=_normalize_evm_network(network),
            account_index=self.account_index,
            sign_only=self.sign_only,
            address=self.address,
        )

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
                "address": resolved_address,
                "accountIndex": self.account_index,
                "network": self.network,
            },
        )
        result = {
            "chain": self.chain,
            "network": self.network,
            "address": str(data.get("address") or resolved_address or ""),
            "balance_wei": str(data.get("balance") or "0"),
            "balance_native": str(data.get("balanceFormatted") or "0"),
            "asset": str(data.get("nativeSymbol") or "ETH"),
            "chain_id": int(data.get("chainId") or 0),
            "source": "wdk-evm-wallet",
        }
        try:
            portfolio = await build_portfolio_snapshot(
                address=result["address"],
                network=self.network,
                native_symbol=result["asset"],
                native_balance_wei=result["balance_wei"],
                native_balance=result["balance_native"],
            )
        except Exception as exc:
            result["portfolio_error"] = str(exc)
            result["tokens"] = []
            result["token_count"] = 0
            result["total_value_usd"] = None
            result["native_price_usd"] = None
            result["native_value_usd"] = None
            return result

        result.update(
            {
                "native_price_usd": portfolio.get("native_price_usd"),
                "native_value_usd": portfolio.get("native_value_usd"),
                "tokens": list(portfolio.get("tokens") or []),
                "token_count": int(portfolio.get("token_count") or 0),
                "total_value_usd": portfolio.get("total_value_usd"),
                "pricing_source": portfolio.get("pricing_source"),
                "token_discovery_source": portfolio.get("token_discovery_source"),
            }
        )
        return result

    async def get_evm_network_info(self) -> dict[str, Any]:
        data = await self.client.get("/v1/evm/network")
        profiles = data.get("profiles") or {}
        return {
            "chain": self.chain,
            "network": self.network,
            "configured_network": self.network,
            "service_active_network": str(data.get("activeNetwork") or "").strip() or None,
            "available_networks": sorted(str(key) for key in profiles.keys()),
            "agent_selectable_networks": ["ethereum", "base"],
            "swap_supported_networks": ["ethereum", "base"],
            "network_profiles": {
                str(network): {
                    **dict(profile),
                    "providerUrl": _sanitize_provider_url((profile or {}).get("providerUrl")),
                }
                for network, profile in profiles.items()
                if isinstance(profile, dict)
            },
            "selected_profile": {
                **dict(data.get("selectedProfile") or {}),
                "providerUrl": _sanitize_provider_url((data.get("selectedProfile") or {}).get("providerUrl")),
            }
            if isinstance(data.get("selectedProfile"), dict)
            else data.get("selectedProfile"),
            "source": "wdk-evm-wallet",
        }

    async def get_mayan_supported_chains(self) -> dict[str, Any]:
        chains = await mayan.fetch_supported_chains()
        items = [
            {
                "name": str(item.get("nameId") or item.get("chainName") or "").strip(),
                "display_name": str(item.get("chainName") or item.get("fullChainName") or "").strip(),
                "full_name": str(item.get("fullChainName") or item.get("chainName") or "").strip(),
                "mode": str(item.get("mode") or "").strip() or None,
                "chain_id": item.get("chainId"),
                "wormhole_chain_id": item.get("wChainId"),
                "currency_symbol": str(item.get("currencySymbol") or "").strip() or None,
                "origin_active": bool(item.get("originActive")),
                "destination_active": bool(item.get("destinationActive")),
                "base_token": item.get("baseToken"),
            }
            for item in chains
        ]
        return {
            "provider": "mayan",
            "chain": "cross-chain",
            "network": "mainnet",
            "chain_count": len(items),
            "chains": items,
            "source": "mayan",
        }

    async def get_mayan_tokens(
        self,
        *,
        chain: str,
        query: str | None = None,
        limit: int = 20,
    ) -> dict[str, Any]:
        normalized_chain = mayan.normalize_chain_name(chain, field_name="chain")
        all_tokens = await mayan.fetch_tokens(chain=normalized_chain)
        text = str(query or "").strip().lower()
        filtered = [
            token
            for token in all_tokens
            if not text
            or text in str(token.get("symbol") or "").lower()
            or text in str(token.get("name") or "").lower()
            or text in str(token.get("contract") or "").lower()
            or text in str(token.get("mint") or "").lower()
        ]
        filtered.sort(
            key=lambda item: (
                0 if item.get("verified") else 1,
                str(item.get("symbol") or ""),
            )
        )
        selected = filtered[:limit]
        return {
            "provider": "mayan",
            "chain": normalized_chain,
            "query": query,
            "count": len(selected),
            "total_matches": len(filtered),
            "tokens": selected,
            "source": "mayan",
        }

    async def get_mayan_quote(
        self,
        *,
        from_chain: str,
        to_chain: str,
        from_token: str,
        to_token: str,
        amount_in_raw: str,
        slippage_bps: int | str = "auto",
        gas_drop: int | float | None = None,
        destination_address: str | None = None,
    ) -> dict[str, Any]:
        payload = await mayan.fetch_quote(
            from_chain=from_chain,
            to_chain=to_chain,
            from_token=from_token,
            to_token=to_token,
            amount_in_raw=amount_in_raw,
            slippage_bps=slippage_bps,
            gas_drop=gas_drop,
            destination_address=destination_address,
        )
        quotes = list(payload.get("quotes") or [])
        best_quote = quotes[0] if quotes else None
        return {
            "provider": "mayan",
            "chain": "cross-chain",
            "network": "mainnet",
            "from_chain": mayan.normalize_chain_name(from_chain, field_name="from_chain"),
            "to_chain": mayan.normalize_chain_name(to_chain, field_name="to_chain"),
            "from_token": from_token,
            "to_token": to_token,
            "amount_in_raw": amount_in_raw,
            "slippage_bps": slippage_bps,
            "gas_drop": gas_drop,
            "destination_address": destination_address,
            "quote_count": len(quotes),
            "best_quote": best_quote,
            "quotes": quotes,
            "minimum_sdk_version": payload.get("minimumSdkVersion"),
            "source": "mayan",
        }

    async def get_mayan_swap_status(self, *, source_tx_hash: str) -> dict[str, Any]:
        payload = await mayan.fetch_swap_status_by_tx_hash(source_tx_hash)
        return {
            "provider": "mayan",
            "chain": "cross-chain",
            "network": "mainnet",
            "source_tx_hash": source_tx_hash,
            "swap": payload,
            "client_status": payload.get("clientStatus") or payload.get("status"),
            "source": "mayan",
        }

    async def get_evm_token_balance(self, token_address: str) -> dict[str, Any]:
        resolved_address = await self.get_address()
        data = await self.client.post(
            "/v1/evm/token-balance/get",
            {
                "walletId": self.wallet_id,
                "address": resolved_address,
                "accountIndex": self.account_index,
                "network": self.network,
                "tokenAddress": token_address,
            },
        )
        return {
            "chain": self.chain,
            "network": self.network,
            "address": str(data.get("address") or resolved_address or ""),
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
        resolved_address = await self.get_address()
        data = await self.client.post(
            "/v1/evm/swap/quote",
            {
                "walletId": self.wallet_id,
                "address": resolved_address,
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
            "address": str(data.get("address") or resolved_address or ""),
            "token_in": str((data.get("swapRequest") or {}).get("tokenIn") or token_in),
            "token_out": str((data.get("swapRequest") or {}).get("tokenOut") or token_out),
            "amount_in_raw": str((data.get("swapRequest") or {}).get("tokenInAmount") or amount_in_raw),
            "amount_in_ui": str(data.get("inputAmountFormatted")) if data.get("inputAmountFormatted") is not None else None,
            "estimated_output_amount_raw": str(quote.get("tokenOutAmount") or "0"),
            "estimated_output_amount_ui": (
                str(data.get("outputAmountFormatted")) if data.get("outputAmountFormatted") is not None else None
            ),
            "quote": quote,
            "protocol": str(data.get("protocol") or "velora"),
            "execution_supported": bool(data.get("executionSupported")) and not self.sign_only,
            "quote_fingerprint": str(data.get("quoteFingerprint") or "").strip() or None,
            "router": str(data.get("router") or "").strip() or None,
            "estimated_fee_wei": (
                str(data.get("estimatedFeeWei"))
                if data.get("estimatedFeeWei") is not None
                else (_extract_fee_wei(quote) if _extract_fee_wei(quote) is not None else None)
            ),
            "estimated_swap_fee_wei": (
                str(data.get("estimatedSwapFeeWei"))
                if data.get("estimatedSwapFeeWei") is not None
                else (_extract_fee_wei(quote) if _extract_fee_wei(quote) is not None else None)
            ),
            "estimated_approval_fee_wei": str(data.get("estimatedApprovalFeeWei") or "0"),
            "fee_estimate_available": bool(data.get("feeEstimateAvailable", True)),
            "fee_estimate_error": data.get("feeEstimateError"),
            "slippage_bps": int(data.get("slippageBps") or 0) if data.get("slippageBps") is not None else None,
            "minimum_output_amount_raw": (
                str(data.get("minimumOutputAmountRaw"))
                if data.get("minimumOutputAmountRaw") is not None
                else None
            ),
            "allowance": _normalize_swap_allowance(data.get("allowance")),
            "simulation": _normalize_swap_simulation(data.get("simulation")),
            "swap_transaction": {
                "to": str((data.get("swapTransaction") or {}).get("to") or "").strip() or None,
                "value": str((data.get("swapTransaction") or {}).get("value") or "0"),
                "data_hash": str((data.get("swapTransaction") or {}).get("dataHash") or "").strip() or None,
            },
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
        resolved_address = await self.get_address()
        data = await self.client.post(
            "/v1/evm/swap/quote",
            {
                "walletId": self.wallet_id,
                "address": resolved_address,
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
            "from_address": resolved_address,
            "token_in": str((data.get("swapRequest") or {}).get("tokenIn") or token_in),
            "token_out": str((data.get("swapRequest") or {}).get("tokenOut") or token_out),
            "input_amount_raw": str((data.get("swapRequest") or {}).get("tokenInAmount") or amount_in_raw),
            "input_amount_ui": str(data.get("inputAmountFormatted")) if data.get("inputAmountFormatted") is not None else None,
            "estimated_output_amount_raw": str(quote.get("tokenOutAmount") or "0"),
            "estimated_output_amount_ui": (
                str(data.get("outputAmountFormatted")) if data.get("outputAmountFormatted") is not None else None
            ),
            "estimated_fee_wei": (
                str(data.get("estimatedFeeWei"))
                if data.get("estimatedFeeWei") is not None
                else (_extract_fee_wei(quote) if _extract_fee_wei(quote) is not None else None)
            ),
            "estimated_swap_fee_wei": (
                str(data.get("estimatedSwapFeeWei"))
                if data.get("estimatedSwapFeeWei") is not None
                else (_extract_fee_wei(quote) if _extract_fee_wei(quote) is not None else None)
            ),
            "estimated_approval_fee_wei": str(data.get("estimatedApprovalFeeWei") or "0"),
            "fee_estimate_available": bool(data.get("feeEstimateAvailable", True)),
            "fee_estimate_error": data.get("feeEstimateError"),
            "slippage_bps": int(data.get("slippageBps") or 0) if data.get("slippageBps") is not None else None,
            "minimum_output_amount_raw": (
                str(data.get("minimumOutputAmountRaw"))
                if data.get("minimumOutputAmountRaw") is not None
                else None
            ),
            "swap_provider": str(data.get("protocol") or "velora"),
            "execution_supported": bool(data.get("executionSupported")) and not self.sign_only,
            "route_plan": _normalize_swap_route(quote),
            "quote_fingerprint": str(data.get("quoteFingerprint") or "").strip() or None,
            "router": str(data.get("router") or "").strip() or None,
            "allowance": _normalize_swap_allowance(data.get("allowance")),
            "simulation": _normalize_swap_simulation(data.get("simulation")),
            "swap_transaction": {
                "to": str((data.get("swapTransaction") or {}).get("to") or "").strip() or None,
                "value": str((data.get("swapTransaction") or {}).get("value") or "0"),
                "data_hash": str((data.get("swapTransaction") or {}).get("dataHash") or "").strip() or None,
            },
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
        expected_quote_fingerprint: str | None = None,
        minimum_output_amount_raw: str | None = None,
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
                **(
                    {"expectedQuoteFingerprint": expected_quote_fingerprint}
                    if isinstance(expected_quote_fingerprint, str) and expected_quote_fingerprint.strip()
                    else {}
                ),
                **(
                    {"minimumTokenOutAmount": minimum_output_amount_raw}
                    if isinstance(minimum_output_amount_raw, str) and minimum_output_amount_raw.strip()
                    else {}
                ),
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
            "estimated_fee_wei": str(data.get("estimatedFeeWei") or result.get("fee") or "0"),
            "estimated_swap_fee_wei": str(data.get("estimatedSwapFeeWei") or result.get("swapFee") or "0"),
            "estimated_approval_fee_wei": str(data.get("estimatedApprovalFeeWei") or result.get("approvalFee") or "0"),
            "slippage_bps": int(data.get("slippageBps") or 0) if data.get("slippageBps") is not None else None,
            "minimum_output_amount_raw": (
                str(data.get("minimumOutputAmountRaw"))
                if data.get("minimumOutputAmountRaw") is not None
                else None
            ),
            "swap_provider": str(data.get("protocol") or "velora"),
            "quote_fingerprint": str(data.get("quoteFingerprint") or "").strip() or None,
            "router": str(data.get("router") or "").strip() or None,
            "allowance": _normalize_swap_allowance(data.get("allowance")),
            "simulation": _normalize_swap_simulation(data.get("simulation")),
            "swap_transaction": {
                "to": str((data.get("swapTransaction") or {}).get("to") or "").strip() or None,
                "value": str((data.get("swapTransaction") or {}).get("value") or "0"),
                "data_hash": str((data.get("swapTransaction") or {}).get("dataHash") or "").strip() or None,
            },
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

    async def preview_evm_cross_chain_swap(
        self,
        *,
        token_in: str,
        destination_chain: str,
        output_token: str,
        destination_address: str,
        amount_in_raw: str,
        slippage_bps: int | str = "auto",
        gas_drop: int | float | None = None,
    ) -> dict[str, Any]:
        resolved_address = await self.get_address()
        data = await self.client.post(
            "/v1/evm/mayan/quote",
            {
                "walletId": self.wallet_id,
                "address": resolved_address,
                "accountIndex": self.account_index,
                "network": self.network,
                "tokenIn": token_in,
                "destinationChain": destination_chain,
                "outputToken": output_token,
                "destinationAddress": destination_address,
                "tokenInAmount": amount_in_raw,
                "slippageBps": slippage_bps,
                **({"gasDrop": gas_drop} if gas_drop is not None else {}),
            },
        )
        quote = dict(data.get("quote") or {})
        return {
            "chain": self.chain,
            "network": self.network,
            "asset_type": "evm-cross-chain-swap",
            "asset": "EVM",
            "wallet": self.wallet_id,
            "from_address": str(data.get("address") or resolved_address or ""),
            "source_chain": str(data.get("sourceChain") or self.network),
            "destination_chain": str(data.get("destinationChain") or destination_chain),
            "token_in": str((data.get("swapRequest") or {}).get("tokenIn") or token_in),
            "output_token": str((data.get("swapRequest") or {}).get("outputToken") or output_token),
            "destination_address": str(
                (data.get("swapRequest") or {}).get("destinationAddress") or destination_address
            ),
            "input_amount_raw": str((data.get("swapRequest") or {}).get("tokenInAmount") or amount_in_raw),
            "input_amount_ui": str(data.get("inputAmountFormatted")) if data.get("inputAmountFormatted") is not None else None,
            "estimated_output_amount_raw": str(
                quote.get("expectedAmountOutBaseUnits")
                or quote.get("minAmountOutBaseUnits")
                or quote.get("minReceivedBaseUnits")
                or "0"
            ),
            "estimated_output_amount_ui": (
                str(data.get("outputAmountFormatted")) if data.get("outputAmountFormatted") is not None else None
            ),
            "estimated_fee_wei": (
                str(data.get("estimatedFeeWei"))
                if data.get("estimatedFeeWei") is not None
                else (_extract_fee_wei(quote) if _extract_fee_wei(quote) is not None else None)
            ),
            "estimated_swap_fee_wei": (
                str(data.get("estimatedSwapFeeWei"))
                if data.get("estimatedSwapFeeWei") is not None
                else (_extract_fee_wei(quote) if _extract_fee_wei(quote) is not None else None)
            ),
            "estimated_approval_fee_wei": str(data.get("estimatedApprovalFeeWei") or "0"),
            "fee_estimate_available": bool(data.get("feeEstimateAvailable", True)),
            "fee_estimate_error": data.get("feeEstimateError"),
            "slippage_bps": int(data.get("slippageBps") or 0) if data.get("slippageBps") is not None else None,
            "gas_drop": gas_drop,
            "minimum_output_amount_raw": (
                str(data.get("minimumOutputAmountRaw"))
                if data.get("minimumOutputAmountRaw") is not None
                else str(quote.get("minAmountOutBaseUnits") or quote.get("minReceivedBaseUnits") or "0")
            ),
            "swap_provider": str(data.get("protocol") or "mayan"),
            "execution_supported": bool(data.get("executionSupported")) and not self.sign_only,
            "route_plan": quote,
            "quote_fingerprint": str(data.get("quoteFingerprint") or "").strip() or None,
            "router": str(data.get("router") or "").strip() or None,
            "quote_type": str(data.get("quoteType") or quote.get("type") or "").strip() or None,
            "quote_id": str(data.get("quoteId") or quote.get("quoteId") or "").strip() or None,
            "allowance": _normalize_swap_allowance(data.get("allowance")),
            "simulation": _normalize_swap_simulation(data.get("simulation")),
            "swap_transaction": {
                "to": str((data.get("swapTransaction") or {}).get("to") or "").strip() or None,
                "value": str((data.get("swapTransaction") or {}).get("value") or "0"),
                "data_hash": str((data.get("swapTransaction") or {}).get("dataHash") or "").strip() or None,
            },
            "token_in_metadata": _normalize_token_metadata(
                data.get("tokenInMetadata"),
                str((data.get("swapRequest") or {}).get("tokenIn") or token_in),
            ),
            "output_token_metadata": _normalize_token_metadata(
                data.get("outputTokenMetadata"),
                str((data.get("swapRequest") or {}).get("outputToken") or output_token),
            ),
            "quote": quote,
            "chain_id": int(data.get("chainId") or 0),
            "source": "wdk-evm-wallet",
        }

    async def send_evm_cross_chain_swap(
        self,
        *,
        token_in: str,
        destination_chain: str,
        output_token: str,
        destination_address: str,
        amount_in_raw: str,
        slippage_bps: int | str = "auto",
        gas_drop: int | float | None = None,
        minimum_output_amount_raw: str | None = None,
    ) -> dict[str, Any]:
        if self.sign_only:
            raise WalletBackendError("wdk_evm_local is configured as sign_only.")
        data = await self.client.post(
            "/v1/evm/mayan/send",
            {
                "walletId": self.wallet_id,
                "accountIndex": self.account_index,
                "network": self.network,
                "tokenIn": token_in,
                "destinationChain": destination_chain,
                "outputToken": output_token,
                "destinationAddress": destination_address,
                "tokenInAmount": amount_in_raw,
                "slippageBps": slippage_bps,
                **({"gasDrop": gas_drop} if gas_drop is not None else {}),
                **(
                    {"minimumTokenOutAmount": minimum_output_amount_raw}
                    if isinstance(minimum_output_amount_raw, str) and minimum_output_amount_raw.strip()
                    else {}
                ),
            },
        )
        result = dict(data.get("result") or {})
        quote = dict(data.get("quote") or {})
        return {
            "chain": self.chain,
            "network": self.network,
            "asset_type": "evm-cross-chain-swap",
            "asset": "EVM",
            "wallet": self.wallet_id,
            "from_address": await self.get_address(),
            "source_chain": str(data.get("sourceChain") or self.network),
            "destination_chain": str(data.get("destinationChain") or destination_chain),
            "token_in": str((data.get("swapRequest") or {}).get("tokenIn") or token_in),
            "output_token": str((data.get("swapRequest") or {}).get("outputToken") or output_token),
            "destination_address": str(
                (data.get("swapRequest") or {}).get("destinationAddress") or destination_address
            ),
            "input_amount_raw": str((data.get("swapRequest") or {}).get("tokenInAmount") or amount_in_raw),
            "input_amount_ui": str(data.get("inputAmountFormatted")) if data.get("inputAmountFormatted") is not None else None,
            "output_amount_raw": str(result.get("tokenOutAmount") or "0"),
            "estimated_output_amount_raw": str(
                result.get("tokenOutAmount")
                or quote.get("expectedAmountOutBaseUnits")
                or quote.get("minAmountOutBaseUnits")
                or "0"
            ),
            "estimated_output_amount_ui": (
                str(data.get("outputAmountFormatted")) if data.get("outputAmountFormatted") is not None else None
            ),
            "estimated_fee_wei": str(data.get("estimatedFeeWei") or result.get("fee") or "0"),
            "estimated_swap_fee_wei": str(data.get("estimatedSwapFeeWei") or result.get("swapFee") or "0"),
            "estimated_approval_fee_wei": str(data.get("estimatedApprovalFeeWei") or result.get("approvalFee") or "0"),
            "slippage_bps": int(data.get("slippageBps") or 0) if data.get("slippageBps") is not None else None,
            "gas_drop": gas_drop,
            "minimum_output_amount_raw": (
                str(data.get("minimumOutputAmountRaw"))
                if data.get("minimumOutputAmountRaw") is not None
                else str(quote.get("minAmountOutBaseUnits") or quote.get("minReceivedBaseUnits") or "0")
            ),
            "swap_provider": str(data.get("protocol") or "mayan"),
            "quote_fingerprint": str(data.get("quoteFingerprint") or "").strip() or None,
            "router": str(data.get("router") or "").strip() or None,
            "quote_type": str(data.get("quoteType") or quote.get("type") or "").strip() or None,
            "quote_id": str(data.get("quoteId") or quote.get("quoteId") or "").strip() or None,
            "allowance": _normalize_swap_allowance(data.get("allowance")),
            "simulation": _normalize_swap_simulation(data.get("simulation")),
            "swap_transaction": {
                "to": str((data.get("swapTransaction") or {}).get("to") or "").strip() or None,
                "value": str((data.get("swapTransaction") or {}).get("value") or "0"),
                "data_hash": str((data.get("swapTransaction") or {}).get("dataHash") or "").strip() or None,
            },
            "token_in_metadata": _normalize_token_metadata(
                data.get("tokenInMetadata"),
                str((data.get("swapRequest") or {}).get("tokenIn") or token_in),
            ),
            "output_token_metadata": _normalize_token_metadata(
                data.get("outputTokenMetadata"),
                str((data.get("swapRequest") or {}).get("outputToken") or output_token),
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
