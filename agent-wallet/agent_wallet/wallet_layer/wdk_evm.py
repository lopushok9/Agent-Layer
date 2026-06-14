"""Local EVM backend backed by the wdk-evm-wallet service."""

from __future__ import annotations

from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from typing import Any

from agent_wallet.config import normalize_evm_network
from agent_wallet.providers.evm_portfolio import build_portfolio_snapshot
from agent_wallet.providers import lifi
from agent_wallet.providers.wdk_evm_local import WdkEvmLocalClient
from agent_wallet.wallet_layer.base import AgentWalletBackend, WalletBackendError, WalletCapabilities


def _normalize_evm_network(value: str | None) -> str:
    return normalize_evm_network(value)


def _lifi_chain_id_for_evm_network(network: str) -> str:
    normalized = _normalize_evm_network(network)
    if normalized == "base":
        return "8453"
    return "1"


def _normalize_x402_typed_data_value(value: Any) -> Any:
    if isinstance(value, (bytes, bytearray)):
        return "0x" + bytes(value).hex()
    if isinstance(value, list):
        return [_normalize_x402_typed_data_value(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _normalize_x402_typed_data_value(item) for key, item in value.items()}
    return value


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


def _normalize_aave_operation(value: str) -> str:
    operation = str(value or "").strip().lower()
    if operation not in {"supply", "withdraw", "borrow", "repay"}:
        raise WalletBackendError("Aave operation must be one of: supply, withdraw, borrow, repay.")
    return operation


def _normalize_lido_operation(value: str) -> str:
    operation = str(value or "").strip().lower()
    if operation not in {"stake_eth_for_wsteth", "wrap_steth", "unwrap_wsteth"}:
        raise WalletBackendError(
            "Lido operation must be one of: stake_eth_for_wsteth, wrap_steth, unwrap_wsteth."
        )
    return operation


def _normalize_lido_withdrawal_operation(value: str) -> str:
    operation = str(value or "").strip().lower()
    if operation not in {"request_withdrawal_steth", "request_withdrawal_wsteth", "claim_withdrawal"}:
        raise WalletBackendError(
            "Lido withdrawal operation must be one of: request_withdrawal_steth, request_withdrawal_wsteth, claim_withdrawal."
        )
    return operation


def _normalize_morpho_vault_operation(value: str) -> str:
    operation = str(value or "").strip().lower()
    if operation not in {"supply", "withdraw"}:
        raise WalletBackendError("Morpho vault operation must be one of: supply, withdraw.")
    return operation


def _normalize_morpho_market_operation(value: str) -> str:
    operation = str(value or "").strip().lower()
    if operation not in {"supply_collateral", "borrow", "repay", "withdraw_collateral"}:
        raise WalletBackendError(
            "Morpho market operation must be one of: supply_collateral, borrow, repay, withdraw_collateral."
        )
    return operation


def _normalize_aave_payload(
    *,
    chain: str,
    network: str,
    wallet_id: str,
    address: str,
    operation: str,
    token_address: str,
    amount_raw: str,
    data: dict[str, Any],
    sign_only: bool,
) -> dict[str, Any]:
    result = dict(data.get("result") or {})
    request = dict(data.get("operationRequest") or {})
    token = str(request.get("token") or token_address)
    amount = str(request.get("amount") or amount_raw)
    return {
        "chain": chain,
        "network": network,
        "asset_type": "evm-aave-v3",
        "asset": "ERC20",
        "wallet": wallet_id,
        "from_address": str(data.get("address") or address),
        "protocol": str(data.get("protocol") or "aave-v3"),
        "operation": str(data.get("operation") or operation),
        "token_address": token,
        "amount_raw": amount,
        "amount_ui": str(data.get("amountFormatted")) if data.get("amountFormatted") is not None else None,
        "estimated_fee_wei": str(data.get("estimatedFeeWei")) if data.get("estimatedFeeWei") is not None else None,
        "estimated_operation_fee_wei": (
            str(data.get("estimatedOperationFeeWei"))
            if data.get("estimatedOperationFeeWei") is not None
            else None
        ),
        "estimated_approval_fee_wei": str(data.get("estimatedApprovalFeeWei") or "0"),
        "fee_estimate_available": bool(data.get("feeEstimateAvailable", True)),
        "fee_estimate_error": data.get("feeEstimateError"),
        "execution_supported": not sign_only,
        "quote_fingerprint": str(data.get("quoteFingerprint") or "").strip() or None,
        "allowance": _normalize_swap_allowance(data.get("allowance")),
        "token_metadata": _normalize_token_metadata(data.get("tokenMetadata"), token),
        "hash": result.get("hash"),
        "approve_hash": result.get("approveHash"),
        "reset_allowance_hash": result.get("resetAllowanceHash"),
        "result": result,
        "chain_id": int(data.get("chainId") or 0),
        "source": "wdk-evm-wallet",
    }


def _normalize_lido_payload(
    *,
    chain: str,
    network: str,
    wallet_id: str,
    address: str,
    operation: str,
    amount_raw: str,
    data: dict[str, Any],
    sign_only: bool,
) -> dict[str, Any]:
    result = dict(data.get("result") or {})
    request = dict(data.get("operationRequest") or {})
    amount = str(request.get("amount") or amount_raw)
    return {
        "chain": chain,
        "network": network,
        "asset_type": "evm-lido-staking",
        "asset": "ETH",
        "wallet": wallet_id,
        "from_address": str(data.get("address") or address),
        "protocol": str(data.get("protocol") or "lido"),
        "operation": str(data.get("operation") or operation),
        "amount_raw": amount,
        "amount_ui": str(data.get("amountFormatted")) if data.get("amountFormatted") is not None else None,
        "expected_output_amount_raw": str(data.get("expectedOutputAmountRaw") or "0"),
        "expected_output_amount_ui": (
            str(data.get("expectedOutputAmountFormatted"))
            if data.get("expectedOutputAmountFormatted") is not None
            else None
        ),
        "estimated_fee_wei": str(data.get("estimatedFeeWei")) if data.get("estimatedFeeWei") is not None else None,
        "estimated_operation_fee_wei": (
            str(data.get("estimatedOperationFeeWei"))
            if data.get("estimatedOperationFeeWei") is not None
            else None
        ),
        "estimated_approval_fee_wei": str(data.get("estimatedApprovalFeeWei") or "0"),
        "fee_estimate_available": bool(data.get("feeEstimateAvailable", True)),
        "fee_estimate_error": data.get("feeEstimateError"),
        "execution_supported": not sign_only,
        "quote_fingerprint": str(data.get("quoteFingerprint") or "").strip() or None,
        "allowance": _normalize_swap_allowance(data.get("allowance")),
        "input_asset": _normalize_token_metadata(data.get("inputAsset")),
        "output_asset": _normalize_token_metadata(data.get("outputAsset")),
        "contracts": dict(data.get("contracts") or {}),
        "referral_address": str(data.get("referralAddress") or "").strip() or None,
        "simulation": _normalize_swap_simulation(data.get("simulation")),
        "hash": result.get("hash"),
        "approve_hash": result.get("approveHash"),
        "reset_allowance_hash": result.get("resetAllowanceHash"),
        "result": result,
        "chain_id": int(data.get("chainId") or 0),
        "source": "wdk-evm-wallet",
    }


def _normalize_lido_withdrawal_payload(
    *,
    chain: str,
    network: str,
    wallet_id: str,
    address: str,
    operation: str,
    amount_raw: str | None,
    request_id: str | None,
    data: dict[str, Any],
    sign_only: bool,
) -> dict[str, Any]:
    result = dict(data.get("result") or {})
    request = dict(data.get("operationRequest") or {})
    resolved_amount = (
        str(request.get("amount"))
        if request.get("amount") is not None
        else (str(amount_raw) if amount_raw is not None else None)
    )
    resolved_request_id = (
        str(request.get("requestId"))
        if request.get("requestId") is not None
        else (str(request_id) if request_id is not None else None)
    )
    return {
        "chain": chain,
        "network": network,
        "asset_type": "evm-lido-withdrawal-queue",
        "asset": "ETH",
        "wallet": wallet_id,
        "from_address": str(data.get("address") or address),
        "protocol": str(data.get("protocol") or "lido"),
        "operation": str(data.get("operation") or operation),
        "amount_raw": resolved_amount,
        "amount_ui": str(data.get("amountFormatted")) if data.get("amountFormatted") is not None else None,
        "request_id": resolved_request_id,
        "queued_steth_amount_raw": (
            str(data.get("queuedStEthAmountRaw")) if data.get("queuedStEthAmountRaw") is not None else None
        ),
        "queued_steth_amount_ui": (
            str(data.get("queuedStEthAmountFormatted"))
            if data.get("queuedStEthAmountFormatted") is not None
            else None
        ),
        "estimated_fee_wei": str(data.get("estimatedFeeWei")) if data.get("estimatedFeeWei") is not None else None,
        "estimated_operation_fee_wei": (
            str(data.get("estimatedOperationFeeWei"))
            if data.get("estimatedOperationFeeWei") is not None
            else None
        ),
        "estimated_approval_fee_wei": str(data.get("estimatedApprovalFeeWei") or "0"),
        "fee_estimate_available": bool(data.get("feeEstimateAvailable", True)),
        "fee_estimate_error": data.get("feeEstimateError"),
        "execution_supported": not sign_only,
        "quote_fingerprint": str(data.get("quoteFingerprint") or "").strip() or None,
        "allowance": _normalize_swap_allowance(data.get("allowance")),
        "input_asset": _normalize_token_metadata(data.get("inputAsset")),
        "queue_asset": _normalize_token_metadata(data.get("queueAsset")),
        "withdrawal_queue": str(data.get("withdrawalQueue") or "").strip() or None,
        "withdrawal_request": dict(data.get("withdrawalRequest") or {}),
        "simulation": _normalize_swap_simulation(data.get("simulation")),
        "hash": result.get("hash"),
        "approve_hash": result.get("approveHash"),
        "reset_allowance_hash": result.get("resetAllowanceHash"),
        "result": result,
        "chain_id": int(data.get("chainId") or 0),
        "source": "wdk-evm-wallet",
    }


def _normalize_morpho_payload(
    *,
    chain: str,
    network: str,
    wallet_id: str,
    address: str,
    operation: str,
    token_address: str,
    amount_raw: str | None,
    native_amount_raw: str | None,
    data: dict[str, Any],
    sign_only: bool,
) -> dict[str, Any]:
    result = dict(data.get("result") or {})
    request = dict(data.get("operationRequest") or {})
    requirements = dict(data.get("requirements") or {})
    resolved_amount = (
        str(request.get("amount"))
        if request.get("amount") is not None
        else (str(amount_raw) if amount_raw is not None else None)
    )
    resolved_native_amount = (
        str(request.get("nativeAmount"))
        if request.get("nativeAmount") is not None
        else (str(native_amount_raw) if native_amount_raw is not None else None)
    )
    target = dict(data.get("target") or {})
    surface = str(data.get("surface") or target.get("type") or "").strip().lower() or None
    asset_type = "evm-morpho-vault" if surface == "vault" else "evm-morpho-market"
    return {
        "chain": chain,
        "network": network,
        "asset_type": asset_type,
        "asset": "ERC20",
        "wallet": wallet_id,
        "from_address": str(data.get("address") or address),
        "protocol": str(data.get("protocol") or "morpho"),
        "surface": surface,
        "operation": str(data.get("operation") or operation),
        "target": target,
        "token_address": str(request.get("token") or token_address),
        "amount_raw": resolved_amount,
        "native_amount_raw": resolved_native_amount,
        "amount_ui": str(data.get("amountFormatted")) if data.get("amountFormatted") is not None else None,
        "native_amount_ui": (
            str(data.get("nativeAmountFormatted"))
            if data.get("nativeAmountFormatted") is not None
            else None
        ),
        "estimated_fee_wei": str(data.get("estimatedFeeWei")) if data.get("estimatedFeeWei") is not None else None,
        "estimated_operation_fee_wei": (
            str(data.get("estimatedOperationFeeWei"))
            if data.get("estimatedOperationFeeWei") is not None
            else None
        ),
        "estimated_requirements_fee_wei": (
            str(data.get("estimatedRequirementsFeeWei"))
            if data.get("estimatedRequirementsFeeWei") is not None
            else None
        ),
        "fee_estimate_available": bool(data.get("feeEstimateAvailable", True)),
        "fee_estimate_error": data.get("feeEstimateError"),
        "execution_supported": bool(data.get("executionSupported", True)) and not sign_only,
        "quote_fingerprint": str(data.get("quoteFingerprint") or "").strip() or None,
        "requirements": {
            "required": bool(requirements.get("required")),
            "requirement_count": int(requirements.get("requirementCount") or 0),
            "approval_required": bool(requirements.get("approvalRequired")),
            "authorization_required": bool(requirements.get("authorizationRequired")),
            "sequence": list(requirements.get("sequence") or []),
        },
        "token_metadata": _normalize_token_metadata(
            data.get("tokenMetadata"),
            str(request.get("token") or token_address),
        ),
        "hash": result.get("hash"),
        "result": result,
        "chain_id": int(data.get("chainId") or 0),
        "source": "wdk-evm-wallet",
    }


def _normalize_lifi_cross_chain_payload(
    *,
    chain: str,
    network: str,
    wallet_id: str,
    data: dict[str, Any],
    token_in: str,
    destination_chain: str,
    output_token: str,
    destination_address: str,
    amount_in_raw: str,
    slippage: float | int | None,
    sign_only: bool,
) -> dict[str, Any]:
    quote = dict(data.get("quote") or {})
    estimate = dict(quote.get("estimate") or {})
    return {
        "chain": chain,
        "network": network,
        "asset_type": "evm-lifi-cross-chain-swap",
        "asset": "EVM",
        "wallet": wallet_id,
        "from_address": str(data.get("address") or ""),
        "source_chain": str(data.get("sourceChain") or network),
        "destination_chain": str(destination_chain or data.get("destinationChain")),
        "destination_chain_id": str(data.get("destinationChainId") or destination_chain),
        "token_in": str((data.get("swapRequest") or {}).get("tokenIn") or token_in),
        "output_token": str((data.get("swapRequest") or {}).get("outputToken") or output_token),
        "destination_address": str(
            (data.get("swapRequest") or {}).get("destinationAddress") or destination_address
        ),
        "input_amount_raw": str((data.get("swapRequest") or {}).get("tokenInAmount") or amount_in_raw),
        "input_amount_ui": str(data.get("inputAmountFormatted")) if data.get("inputAmountFormatted") is not None else None,
        "estimated_output_amount_raw": str(estimate.get("toAmount") or data.get("minimumOutputAmountRaw") or "0"),
        "estimated_output_amount_ui": (
            str(data.get("outputAmountFormatted")) if data.get("outputAmountFormatted") is not None else None
        ),
        "estimated_fee_wei": str(data.get("estimatedFeeWei")) if data.get("estimatedFeeWei") is not None else None,
        "estimated_swap_fee_wei": str(data.get("estimatedSwapFeeWei")) if data.get("estimatedSwapFeeWei") is not None else None,
        "estimated_approval_fee_wei": str(data.get("estimatedApprovalFeeWei") or "0"),
        "fee_estimate_available": bool(data.get("feeEstimateAvailable", True)),
        "fee_estimate_error": data.get("feeEstimateError"),
        "slippage": data.get("slippage") if data.get("slippage") is not None else slippage,
        "minimum_output_amount_raw": str(data.get("minimumOutputAmountRaw") or estimate.get("toAmountMin") or "0"),
        "swap_provider": str(data.get("protocol") or "lifi"),
        "execution_supported": bool(data.get("executionSupported")) and not sign_only,
        "route_plan": quote,
        "quote_fingerprint": str(data.get("quoteFingerprint") or "").strip() or None,
        "router": str(data.get("router") or "").strip() or None,
        "quote_type": str(data.get("quoteType") or quote.get("type") or "").strip() or None,
        "quote_id": str(data.get("quoteId") or quote.get("id") or "").strip() or None,
        "tool": str(data.get("tool") or quote.get("tool") or "").strip() or None,
        "tool_details": data.get("toolDetails") or quote.get("toolDetails"),
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

    def sign_x402_evm_exact_typed_data(
        self,
        *,
        domain: dict[str, Any],
        types: dict[str, Any],
        primary_type: str,
        message: dict[str, Any],
    ) -> bytes:
        data = self.client.post_sync(
            "/v1/evm/x402/exact/sign",
            {
                "walletId": self.wallet_id,
                "accountIndex": self.account_index,
                "network": self.network,
                "domain": domain,
                "types": types,
                "primaryType": primary_type,
                "message": _normalize_x402_typed_data_value(message),
            },
        )
        signature = str(data.get("signature") or "").strip()
        if not signature:
            raise WalletBackendError("wdk-evm-wallet did not return an x402 EVM signature.")
        if signature.startswith("0x"):
            signature = signature[2:]
        try:
            return bytes.fromhex(signature)
        except ValueError as exc:
            raise WalletBackendError("wdk-evm-wallet returned an invalid x402 EVM signature.") from exc

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
            result["assets"] = [
                {
                    "asset_type": "native",
                    "symbol": result["asset"],
                    "amount_raw": result["balance_wei"],
                    "amount_ui": result["balance_native"],
                    "price_usd": None,
                    "value_usd": None,
                    "pricing_source": None,
                }
            ]
            result["asset_count"] = 1
            result["priced_asset_count"] = 0
            result["balance_usd"] = None
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
                "assets": list(portfolio.get("assets") or []),
                "asset_count": int(portfolio.get("asset_count") or 0),
                "priced_asset_count": int(portfolio.get("priced_asset_count") or 0),
                "balance_usd": portfolio.get("balance_usd"),
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

    async def get_lifi_supported_chains(self) -> dict[str, Any]:
        chains = await lifi.fetch_supported_chains()
        supported = lifi.format_openclaw_supported_chains(chains)
        return {
            "provider": "lifi",
            "chain": "cross-chain",
            "network": "mainnet",
            "supported_by_openclaw": lifi.OPENCLAW_SUPPORTED_CHAINS,
            "chain_count": len(supported),
            "chains": supported,
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
    ) -> dict[str, Any]:
        from_chain_id = lifi.normalize_chain_id(from_chain, field_name="from_chain")
        to_chain_id = lifi.normalize_chain_id(to_chain, field_name="to_chain")
        current_chain_id = _lifi_chain_id_for_evm_network(self.network)
        resolved_from_address = str(from_address or "").strip()
        resolved_to_address = str(to_address or "").strip()
        wallet_address: str | None = None
        if from_chain_id == current_chain_id and not resolved_from_address:
            wallet_address = await self.get_address()
            resolved_from_address = str(wallet_address or "").strip()
        if to_chain_id == current_chain_id and not resolved_to_address:
            wallet_address = wallet_address or await self.get_address()
            resolved_to_address = str(wallet_address or "").strip()
        if not resolved_from_address:
            raise WalletBackendError("from_address is required when the LI.FI source chain is not the active EVM network.")
        if not resolved_to_address:
            raise WalletBackendError("to_address is required when the LI.FI destination chain is not the active EVM network.")

        payload = await lifi.fetch_quote(
            from_chain=from_chain_id,
            to_chain=to_chain_id,
            from_token=from_token,
            to_token=to_token,
            amount_in_raw=amount_in_raw,
            from_address=resolved_from_address,
            to_address=resolved_to_address,
            slippage=slippage,
            allow_bridges=allow_bridges,
            deny_bridges=deny_bridges,
            prefer_bridges=prefer_bridges,
        )
        return {
            "provider": "lifi",
            "chain": "cross-chain",
            "network": "mainnet",
            "active_evm_network": self.network,
            "from_chain": lifi.chain_name_for_id(from_chain_id),
            "to_chain": lifi.chain_name_for_id(to_chain_id),
            "from_chain_id": from_chain_id,
            "to_chain_id": to_chain_id,
            "from_token": lifi.normalize_token_address(from_token, chain_id=from_chain_id),
            "to_token": lifi.normalize_token_address(to_token, chain_id=to_chain_id),
            "amount_in_raw": amount_in_raw,
            "from_address": resolved_from_address,
            "to_address": resolved_to_address,
            "slippage": slippage,
            "allow_bridges": allow_bridges,
            "deny_bridges": deny_bridges,
            "prefer_bridges": prefer_bridges,
            "tool": payload.get("tool"),
            "tool_details": payload.get("toolDetails"),
            "action": payload.get("action"),
            "estimate": payload.get("estimate"),
            "included_steps": payload.get("includedSteps"),
            "transaction_request": payload.get("transactionRequest"),
            "quote": payload,
            "source": "lifi",
        }

    async def get_lifi_transfer_status(
        self,
        *,
        tx_hash: str,
        bridge: str | None = None,
        from_chain: str | None = None,
        to_chain: str | None = None,
    ) -> dict[str, Any]:
        payload = await lifi.fetch_transfer_status(
            tx_hash=tx_hash,
            bridge=bridge,
            from_chain=from_chain,
            to_chain=to_chain,
        )
        return {
            "provider": "lifi",
            "chain": "cross-chain",
            "network": "mainnet",
            "tx_hash": tx_hash,
            "bridge": bridge,
            "from_chain": from_chain,
            "to_chain": to_chain,
            "status": payload.get("status"),
            "substatus": payload.get("substatus"),
            "sending": payload.get("sending"),
            "receiving": payload.get("receiving"),
            "transfer": payload,
            "source": "lifi",
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

    async def get_evm_aave_account(self) -> dict[str, Any]:
        resolved_address = await self.get_address()
        data = await self.client.post(
            "/v1/evm/aave/account/get",
            {
                "walletId": self.wallet_id,
                "address": resolved_address,
                "accountIndex": self.account_index,
                "network": self.network,
            },
        )
        return {
            "chain": self.chain,
            "network": self.network,
            "address": str(data.get("address") or resolved_address or ""),
            "protocol": str(data.get("protocol") or "aave-v3"),
            "account_data": dict(data.get("accountData") or {}),
            "chain_id": int(data.get("chainId") or 0),
            "source": "wdk-evm-wallet",
        }

    async def get_evm_aave_reserves(self) -> dict[str, Any]:
        data = await self.client.post(
            "/v1/evm/aave/reserves/get",
            {
                "walletId": self.wallet_id,
                "accountIndex": self.account_index,
                "network": self.network,
            },
        )
        return {
            "chain": self.chain,
            "network": self.network,
            "protocol": str(data.get("protocol") or "aave-v3"),
            "chain_id": int(data.get("chainId") or 0),
            "pool": str(data.get("pool") or "").strip() or None,
            "pool_addresses_provider": str(data.get("poolAddressesProvider") or "").strip() or None,
            "ui_pool_data_provider": str(data.get("uiPoolDataProvider") or "").strip() or None,
            "price_oracle": str(data.get("priceOracle") or "").strip() or None,
            "base_currency_info": dict(data.get("baseCurrencyInfo") or {}),
            "reserve_count": int(data.get("reserveCount") or 0),
            "reserves": list(data.get("reserves") or []),
            "source": "wdk-evm-wallet",
        }

    async def get_evm_aave_positions(self) -> dict[str, Any]:
        resolved_address = await self.get_address()
        data = await self.client.post(
            "/v1/evm/aave/positions/get",
            {
                "walletId": self.wallet_id,
                "address": resolved_address,
                "accountIndex": self.account_index,
                "network": self.network,
            },
        )
        return {
            "chain": self.chain,
            "network": self.network,
            "address": str(data.get("address") or resolved_address or ""),
            "protocol": str(data.get("protocol") or "aave-v3"),
            "chain_id": int(data.get("chainId") or 0),
            "emode_category_id": str(data.get("eModeCategoryId") or "0"),
            "account_data": dict(data.get("accountData") or {}),
            "base_currency_info": dict(data.get("baseCurrencyInfo") or {}),
            "position_count": int(data.get("positionCount") or 0),
            "positions": list(data.get("positions") or []),
            "source": "wdk-evm-wallet",
        }

    async def get_evm_lido_overview(self) -> dict[str, Any]:
        resolved_address = await self.get_address()
        data = await self.client.post(
            "/v1/evm/lido/overview/get",
            {
                "walletId": self.wallet_id,
                "address": resolved_address,
                "accountIndex": self.account_index,
                "network": self.network,
            },
        )
        return {
            "chain": self.chain,
            "network": self.network,
            "protocol": str(data.get("protocol") or "lido"),
            "preferred_position_token": str(data.get("preferredPositionToken") or "wstETH"),
            "chain_id": int(data.get("chainId") or 0),
            "staking_asset": dict(data.get("stakingAsset") or {}),
            "referral_address": str(data.get("referralAddress") or "").strip() or None,
            "contracts": dict(data.get("contracts") or {}),
            "steth_metadata": dict(data.get("stEthMetadata") or {}),
            "wsteth_metadata": dict(data.get("wstEthMetadata") or {}),
            "sample_rates": dict(data.get("sampleRates") or {}),
            "staking_apr": dict(data.get("stakingApr") or {}) if isinstance(data.get("stakingApr"), dict) else None,
            "staking_apr_error": (
                dict(data.get("stakingAprError") or {})
                if isinstance(data.get("stakingAprError"), dict)
                else None
            ),
            "source": "wdk-evm-wallet",
        }

    async def get_evm_lido_positions(self) -> dict[str, Any]:
        resolved_address = await self.get_address()
        data = await self.client.post(
            "/v1/evm/lido/positions/get",
            {
                "walletId": self.wallet_id,
                "address": resolved_address,
                "accountIndex": self.account_index,
                "network": self.network,
            },
        )
        return {
            "chain": self.chain,
            "network": self.network,
            "address": str(data.get("address") or resolved_address or ""),
            "protocol": str(data.get("protocol") or "lido"),
            "preferred_position_token": str(data.get("preferredPositionToken") or "wstETH"),
            "chain_id": int(data.get("chainId") or 0),
            "contracts": dict(data.get("contracts") or {}),
            "native_balance_wei": str(data.get("nativeBalanceWei") or "0"),
            "native_balance_ui": str(data.get("nativeBalanceFormatted") or "0"),
            "steth_equivalent_total_raw": str(data.get("stEthEquivalentTotalRaw") or "0"),
            "steth_equivalent_total_ui": str(data.get("stEthEquivalentTotalFormatted") or "0"),
            "position_count": int(data.get("positionCount") or 0),
            "positions": list(data.get("positions") or []),
            "source": "wdk-evm-wallet",
        }

    async def get_evm_lido_withdrawal_requests(self) -> dict[str, Any]:
        resolved_address = await self.get_address()
        data = await self.client.post(
            "/v1/evm/lido/withdrawals/get",
            {
                "walletId": self.wallet_id,
                "address": resolved_address,
                "accountIndex": self.account_index,
                "network": self.network,
            },
        )
        return {
            "chain": self.chain,
            "network": self.network,
            "address": str(data.get("address") or resolved_address or ""),
            "protocol": str(data.get("protocol") or "lido"),
            "chain_id": int(data.get("chainId") or 0),
            "withdrawal_queue": str(data.get("withdrawalQueue") or "").strip() or None,
            "request_count": int(data.get("requestCount") or 0),
            "claimable_count": int(data.get("claimableCount") or 0),
            "requests": list(data.get("requests") or []),
            "source": "wdk-evm-wallet",
        }

    async def get_evm_morpho_vaults(
        self,
        *,
        vault_address: str | None = None,
        limit: int | None = None,
        listed_only: bool = True,
        asset_address: str | None = None,
        order_by: str | None = None,
        order_direction: str | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "network": self.network,
            "listedOnly": bool(listed_only),
        }
        if isinstance(vault_address, str) and vault_address.strip():
            payload["vaultAddress"] = vault_address.strip()
        if limit is not None:
            payload["limit"] = int(limit)
        if isinstance(asset_address, str) and asset_address.strip():
            payload["assetAddress"] = asset_address.strip()
        if isinstance(order_by, str) and order_by.strip():
            payload["orderBy"] = order_by.strip()
        if isinstance(order_direction, str) and order_direction.strip():
            payload["orderDirection"] = order_direction.strip()
        data = await self.client.post("/v1/evm/morpho/vaults/get", payload)
        return {
            "chain": self.chain,
            "network": self.network,
            "protocol": str(data.get("protocol") or "morpho"),
            "chain_id": int(data.get("chainId") or 0),
            "listed_only": bool(data.get("listedOnly", listed_only)),
            "requested_limit": int(data.get("requestedLimit") or 0),
            "order_by": data.get("orderBy"),
            "order_direction": data.get("orderDirection"),
            "asset_address_filter": data.get("assetAddressFilter"),
            "found": bool(data.get("found")) if "found" in data else None,
            "vault_count": int(data.get("vaultCount") or 0),
            "vault": dict(data.get("vault") or {}) if isinstance(data.get("vault"), dict) else None,
            "vaults": list(data.get("vaults") or []),
            "source": "wdk-evm-wallet",
        }

    async def get_evm_morpho_markets(
        self,
        *,
        market_id: str | None = None,
        limit: int | None = None,
        listed_only: bool = True,
        search: str | None = None,
        collateral_asset_address: str | None = None,
        loan_asset_address: str | None = None,
        order_by: str | None = None,
        order_direction: str | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "network": self.network,
            "listedOnly": bool(listed_only),
        }
        if isinstance(market_id, str) and market_id.strip():
            payload["marketId"] = market_id.strip()
        if limit is not None:
            payload["limit"] = int(limit)
        if isinstance(search, str) and search.strip():
            payload["search"] = search.strip()
        if isinstance(collateral_asset_address, str) and collateral_asset_address.strip():
            payload["collateralAssetAddress"] = collateral_asset_address.strip()
        if isinstance(loan_asset_address, str) and loan_asset_address.strip():
            payload["loanAssetAddress"] = loan_asset_address.strip()
        if isinstance(order_by, str) and order_by.strip():
            payload["orderBy"] = order_by.strip()
        if isinstance(order_direction, str) and order_direction.strip():
            payload["orderDirection"] = order_direction.strip()
        data = await self.client.post("/v1/evm/morpho/markets/get", payload)
        return {
            "chain": self.chain,
            "network": self.network,
            "protocol": str(data.get("protocol") or "morpho"),
            "chain_id": int(data.get("chainId") or 0),
            "listed_only": bool(data.get("listedOnly", listed_only)),
            "requested_limit": int(data.get("requestedLimit") or 0),
            "order_by": data.get("orderBy"),
            "order_direction": data.get("orderDirection"),
            "search": data.get("search"),
            "collateral_asset_filter": data.get("collateralAssetFilter"),
            "loan_asset_filter": data.get("loanAssetFilter"),
            "found": bool(data.get("found")) if "found" in data else None,
            "market_count": int(data.get("marketCount") or 0),
            "market": dict(data.get("market") or {}) if isinstance(data.get("market"), dict) else None,
            "markets": list(data.get("markets") or []),
            "source": "wdk-evm-wallet",
        }

    async def get_evm_morpho_positions(self) -> dict[str, Any]:
        resolved_address = await self.get_address()
        data = await self.client.post(
            "/v1/evm/morpho/positions/get",
            {
                "walletId": self.wallet_id,
                "address": resolved_address,
                "accountIndex": self.account_index,
                "network": self.network,
            },
        )
        return {
            "chain": self.chain,
            "network": self.network,
            "address": str(data.get("address") or resolved_address or ""),
            "protocol": str(data.get("protocol") or "morpho"),
            "chain_id": int(data.get("chainId") or 0),
            "market_position_count": int(data.get("marketPositionCount") or 0),
            "vault_position_count": int(data.get("vaultPositionCount") or 0),
            "market_positions": list(data.get("marketPositions") or []),
            "vault_positions": list(data.get("vaultPositions") or []),
            "source": "wdk-evm-wallet",
        }

    async def preview_evm_aave_operation(
        self,
        *,
        operation: str,
        token_address: str,
        amount_raw: str,
    ) -> dict[str, Any]:
        normalized_operation = _normalize_aave_operation(operation)
        resolved_address = await self.get_address()
        data = await self.client.post(
            f"/v1/evm/aave/{normalized_operation}/quote",
            {
                "walletId": self.wallet_id,
                "address": resolved_address,
                "accountIndex": self.account_index,
                "network": self.network,
                "tokenAddress": token_address,
                "amount": amount_raw,
            },
        )
        return _normalize_aave_payload(
            chain=self.chain,
            network=self.network,
            wallet_id=self.wallet_id,
            address=resolved_address,
            operation=normalized_operation,
            token_address=token_address,
            amount_raw=amount_raw,
            data=data,
            sign_only=self.sign_only,
        )

    async def send_evm_aave_operation(
        self,
        *,
        operation: str,
        token_address: str,
        amount_raw: str,
        expected_quote_fingerprint: str | None = None,
    ) -> dict[str, Any]:
        if self.sign_only:
            raise WalletBackendError("wdk_evm_local is configured as sign_only.")
        normalized_operation = _normalize_aave_operation(operation)
        data = await self.client.post(
            f"/v1/evm/aave/{normalized_operation}/send",
            {
                "walletId": self.wallet_id,
                "accountIndex": self.account_index,
                "network": self.network,
                "tokenAddress": token_address,
                "amount": amount_raw,
                **(
                    {"expectedQuoteFingerprint": expected_quote_fingerprint}
                    if isinstance(expected_quote_fingerprint, str) and expected_quote_fingerprint.strip()
                    else {}
                ),
            },
        )
        return {
            **_normalize_aave_payload(
                chain=self.chain,
                network=self.network,
                wallet_id=self.wallet_id,
                address=await self.get_address(),
                operation=normalized_operation,
                token_address=token_address,
                amount_raw=amount_raw,
                data=data,
                sign_only=self.sign_only,
            ),
            "broadcasted": True,
            "confirmed": False,
        }

    async def preview_evm_lido_operation(
        self,
        *,
        operation: str,
        amount_raw: str,
    ) -> dict[str, Any]:
        normalized_operation = _normalize_lido_operation(operation)
        resolved_address = await self.get_address()
        data = await self.client.post(
            f"/v1/evm/lido/{normalized_operation}/quote",
            {
                "walletId": self.wallet_id,
                "address": resolved_address,
                "accountIndex": self.account_index,
                "network": self.network,
                "amount": amount_raw,
            },
        )
        return _normalize_lido_payload(
            chain=self.chain,
            network=self.network,
            wallet_id=self.wallet_id,
            address=resolved_address,
            operation=normalized_operation,
            amount_raw=amount_raw,
            data=data,
            sign_only=self.sign_only,
        )

    async def send_evm_lido_operation(
        self,
        *,
        operation: str,
        amount_raw: str,
        expected_quote_fingerprint: str | None = None,
    ) -> dict[str, Any]:
        if self.sign_only:
            raise WalletBackendError("wdk_evm_local is configured as sign_only.")
        normalized_operation = _normalize_lido_operation(operation)
        data = await self.client.post(
            f"/v1/evm/lido/{normalized_operation}/send",
            {
                "walletId": self.wallet_id,
                "accountIndex": self.account_index,
                "network": self.network,
                "amount": amount_raw,
                **(
                    {"expectedQuoteFingerprint": expected_quote_fingerprint}
                    if isinstance(expected_quote_fingerprint, str) and expected_quote_fingerprint.strip()
                    else {}
                ),
            },
        )
        return {
            **_normalize_lido_payload(
                chain=self.chain,
                network=self.network,
                wallet_id=self.wallet_id,
                address=await self.get_address(),
                operation=normalized_operation,
                amount_raw=amount_raw,
                data=data,
                sign_only=self.sign_only,
            ),
            "broadcasted": True,
            "confirmed": False,
        }

    async def preview_evm_lido_withdrawal(
        self,
        *,
        operation: str,
        amount_raw: str | None = None,
        request_id: str | None = None,
    ) -> dict[str, Any]:
        normalized_operation = _normalize_lido_withdrawal_operation(operation)
        resolved_address = await self.get_address()
        payload: dict[str, Any] = {
            "walletId": self.wallet_id,
            "address": resolved_address,
            "accountIndex": self.account_index,
            "network": self.network,
        }
        if amount_raw is not None:
            payload["amount"] = amount_raw
        if request_id is not None:
            payload["requestId"] = request_id
        data = await self.client.post(
            f"/v1/evm/lido/{normalized_operation}/quote",
            payload,
        )
        return _normalize_lido_withdrawal_payload(
            chain=self.chain,
            network=self.network,
            wallet_id=self.wallet_id,
            address=resolved_address,
            operation=normalized_operation,
            amount_raw=amount_raw,
            request_id=request_id,
            data=data,
            sign_only=self.sign_only,
        )

    async def send_evm_lido_withdrawal(
        self,
        *,
        operation: str,
        amount_raw: str | None = None,
        request_id: str | None = None,
        expected_quote_fingerprint: str | None = None,
    ) -> dict[str, Any]:
        if self.sign_only:
            raise WalletBackendError("wdk_evm_local is configured as sign_only.")
        normalized_operation = _normalize_lido_withdrawal_operation(operation)
        payload: dict[str, Any] = {
            "walletId": self.wallet_id,
            "accountIndex": self.account_index,
            "network": self.network,
        }
        if amount_raw is not None:
            payload["amount"] = amount_raw
        if request_id is not None:
            payload["requestId"] = request_id
        if isinstance(expected_quote_fingerprint, str) and expected_quote_fingerprint.strip():
            payload["expectedQuoteFingerprint"] = expected_quote_fingerprint
        data = await self.client.post(
            f"/v1/evm/lido/{normalized_operation}/send",
            payload,
        )
        return {
            **_normalize_lido_withdrawal_payload(
                chain=self.chain,
                network=self.network,
                wallet_id=self.wallet_id,
                address=await self.get_address(),
                operation=normalized_operation,
                amount_raw=amount_raw,
                request_id=request_id,
                data=data,
                sign_only=self.sign_only,
            ),
            "broadcasted": True,
            "confirmed": False,
        }

    async def preview_evm_morpho_vault_operation(
        self,
        *,
        operation: str,
        token_address: str,
        vault_address: str | None = None,
        vault_preset: str | None = None,
        amount_raw: str | None = None,
        native_amount_raw: str | None = None,
    ) -> dict[str, Any]:
        normalized_operation = _normalize_morpho_vault_operation(operation)
        resolved_address = await self.get_address()
        payload: dict[str, Any] = {
            "walletId": self.wallet_id,
            "address": resolved_address,
            "accountIndex": self.account_index,
            "network": self.network,
            "tokenAddress": token_address,
        }
        if isinstance(vault_address, str) and vault_address.strip():
            payload["vaultAddress"] = vault_address.strip()
        if isinstance(vault_preset, str) and vault_preset.strip():
            payload["vaultPreset"] = vault_preset.strip()
        if amount_raw is not None:
            payload["amount"] = amount_raw
        if native_amount_raw is not None:
            payload["nativeAmount"] = native_amount_raw
        data = await self.client.post(
            f"/v1/evm/morpho/vault/{normalized_operation}/quote",
            payload,
        )
        return _normalize_morpho_payload(
            chain=self.chain,
            network=self.network,
            wallet_id=self.wallet_id,
            address=resolved_address,
            operation=normalized_operation,
            token_address=token_address,
            amount_raw=amount_raw,
            native_amount_raw=native_amount_raw,
            data=data,
            sign_only=self.sign_only,
        )

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
    ) -> dict[str, Any]:
        if self.sign_only:
            raise WalletBackendError("wdk_evm_local is configured as sign_only.")
        normalized_operation = _normalize_morpho_vault_operation(operation)
        payload: dict[str, Any] = {
            "walletId": self.wallet_id,
            "accountIndex": self.account_index,
            "network": self.network,
            "tokenAddress": token_address,
        }
        if isinstance(vault_address, str) and vault_address.strip():
            payload["vaultAddress"] = vault_address.strip()
        if isinstance(vault_preset, str) and vault_preset.strip():
            payload["vaultPreset"] = vault_preset.strip()
        if amount_raw is not None:
            payload["amount"] = amount_raw
        if native_amount_raw is not None:
            payload["nativeAmount"] = native_amount_raw
        if isinstance(expected_quote_fingerprint, str) and expected_quote_fingerprint.strip():
            payload["expectedQuoteFingerprint"] = expected_quote_fingerprint.strip()
        data = await self.client.post(
            f"/v1/evm/morpho/vault/{normalized_operation}/send",
            payload,
        )
        return {
            **_normalize_morpho_payload(
                chain=self.chain,
                network=self.network,
                wallet_id=self.wallet_id,
                address=await self.get_address(),
                operation=normalized_operation,
                token_address=token_address,
                amount_raw=amount_raw,
                native_amount_raw=native_amount_raw,
                data=data,
                sign_only=self.sign_only,
            ),
            "broadcasted": True,
            "confirmed": False,
        }

    async def preview_evm_morpho_market_operation(
        self,
        *,
        operation: str,
        token_address: str,
        market_id: str | None = None,
        market_preset: str | None = None,
        amount_raw: str | None = None,
        native_amount_raw: str | None = None,
    ) -> dict[str, Any]:
        normalized_operation = _normalize_morpho_market_operation(operation)
        resolved_address = await self.get_address()
        payload: dict[str, Any] = {
            "walletId": self.wallet_id,
            "address": resolved_address,
            "accountIndex": self.account_index,
            "network": self.network,
            "tokenAddress": token_address,
        }
        if isinstance(market_id, str) and market_id.strip():
            payload["marketId"] = market_id.strip()
        if isinstance(market_preset, str) and market_preset.strip():
            payload["marketPreset"] = market_preset.strip()
        if amount_raw is not None:
            payload["amount"] = amount_raw
        if native_amount_raw is not None:
            payload["nativeAmount"] = native_amount_raw
        data = await self.client.post(
            f"/v1/evm/morpho/market/{normalized_operation}/quote",
            payload,
        )
        return _normalize_morpho_payload(
            chain=self.chain,
            network=self.network,
            wallet_id=self.wallet_id,
            address=resolved_address,
            operation=normalized_operation,
            token_address=token_address,
            amount_raw=amount_raw,
            native_amount_raw=native_amount_raw,
            data=data,
            sign_only=self.sign_only,
        )

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
    ) -> dict[str, Any]:
        if self.sign_only:
            raise WalletBackendError("wdk_evm_local is configured as sign_only.")
        normalized_operation = _normalize_morpho_market_operation(operation)
        payload: dict[str, Any] = {
            "walletId": self.wallet_id,
            "accountIndex": self.account_index,
            "network": self.network,
            "tokenAddress": token_address,
        }
        if isinstance(market_id, str) and market_id.strip():
            payload["marketId"] = market_id.strip()
        if isinstance(market_preset, str) and market_preset.strip():
            payload["marketPreset"] = market_preset.strip()
        if amount_raw is not None:
            payload["amount"] = amount_raw
        if native_amount_raw is not None:
            payload["nativeAmount"] = native_amount_raw
        if isinstance(expected_quote_fingerprint, str) and expected_quote_fingerprint.strip():
            payload["expectedQuoteFingerprint"] = expected_quote_fingerprint.strip()
        data = await self.client.post(
            f"/v1/evm/morpho/market/{normalized_operation}/send",
            payload,
        )
        return {
            **_normalize_morpho_payload(
                chain=self.chain,
                network=self.network,
                wallet_id=self.wallet_id,
                address=await self.get_address(),
                operation=normalized_operation,
                token_address=token_address,
                amount_raw=amount_raw,
                native_amount_raw=native_amount_raw,
                data=data,
                sign_only=self.sign_only,
            ),
            "broadcasted": True,
            "confirmed": False,
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

    def _normalize_uniswap_quote_payload(self, data: dict[str, Any], token_in: str, token_out: str, amount_in_raw: str) -> dict[str, Any]:
        return {
            "chain": self.chain,
            "network": self.network,
            "address": str(data.get("address") or ""),
            "token_in": str(data.get("tokenIn") or token_in),
            "token_out": str(data.get("tokenOut") or token_out),
            "amount_in_raw": str(data.get("tokenInAmount") or amount_in_raw),
            "amount_in_ui": str(data.get("inputAmountFormatted")) if data.get("inputAmountFormatted") is not None else None,
            "estimated_output_amount_raw": str(data.get("outputAmount") or "0"),
            "estimated_output_amount_ui": str(data.get("outputAmountFormatted")) if data.get("outputAmountFormatted") is not None else None,
            "minimum_output_amount_raw": str(data.get("minimumOutputAmountRaw")) if data.get("minimumOutputAmountRaw") is not None else None,
            "slippage_bps": int(data.get("slippageBps")) if data.get("slippageBps") is not None else None,
            "protocol": str(data.get("protocol") or "uniswap"),
            "routing": str(data.get("routing") or "CLASSIC"),
            "permit_required": bool(data.get("permitRequired")),
            "allowance": _normalize_swap_allowance(data.get("allowance")),
            "router": str(data.get("router") or "").strip() or None,
            "quote_fingerprint": str(data.get("quoteFingerprint") or "").strip() or None,
            "gas_fee_usd": str(data.get("gasFeeUSD")) if data.get("gasFeeUSD") is not None else None,
            "estimated_fee_wei": str(data.get("estimatedFeeWei")) if data.get("estimatedFeeWei") is not None else None,
            "execution_supported": bool(data.get("executionSupported")) and not self.sign_only,
            "token_in_metadata": _normalize_token_metadata(data.get("tokenInMetadata"), token_in),
            "token_out_metadata": _normalize_token_metadata(data.get("tokenOutMetadata"), token_out),
            "chain_id": int(data.get("chainId") or 0),
            "source": "wdk-evm-wallet",
        }

    async def get_uniswap_swap_quote(
        self,
        *,
        token_in: str,
        token_out: str,
        amount_in_raw: str,
        slippage_bps: int | None = None,
    ) -> dict[str, Any]:
        resolved_address = await self.get_address()
        body: dict[str, Any] = {
            "walletId": self.wallet_id,
            "address": resolved_address,
            "accountIndex": self.account_index,
            "network": self.network,
            "tokenIn": token_in,
            "tokenOut": token_out,
            "tokenInAmount": amount_in_raw,
        }
        if slippage_bps is not None:
            body["slippageBps"] = slippage_bps
        data = await self.client.post("/v1/evm/uniswap/swap/quote", body)
        return self._normalize_uniswap_quote_payload(data, token_in, token_out, amount_in_raw)

    async def preview_uniswap_swap(
        self,
        *,
        token_in: str,
        token_out: str,
        amount_in_raw: str,
        slippage_bps: int | None = None,
    ) -> dict[str, Any]:
        resolved_address = await self.get_address()
        body: dict[str, Any] = {
            "walletId": self.wallet_id,
            "address": resolved_address,
            "accountIndex": self.account_index,
            "network": self.network,
            "tokenIn": token_in,
            "tokenOut": token_out,
            "tokenInAmount": amount_in_raw,
        }
        if slippage_bps is not None:
            body["slippageBps"] = slippage_bps
        data = await self.client.post("/v1/evm/uniswap/swap/quote", body)
        payload = self._normalize_uniswap_quote_payload(data, token_in, token_out, amount_in_raw)
        return {
            **payload,
            "asset_type": "evm-uniswap-swap",
            "asset": "ERC20",
            "wallet": self.wallet_id,
            "from_address": resolved_address,
            "input_amount_raw": payload["amount_in_raw"],
            "input_amount_ui": payload["amount_in_ui"],
            "swap_provider": payload["protocol"],
            "route_plan": None,
            "swap_transaction": {
                "to": payload["router"],
                "value": "0",
                "data_hash": None,
            },
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
    ) -> dict[str, Any]:
        if self.sign_only:
            raise WalletBackendError("wdk_evm_local is configured as sign_only.")
        body: dict[str, Any] = {
            "walletId": self.wallet_id,
            "accountIndex": self.account_index,
            "network": self.network,
            "tokenIn": token_in,
            "tokenOut": token_out,
            "tokenInAmount": amount_in_raw,
        }
        if slippage_bps is not None:
            body["slippageBps"] = slippage_bps
        if isinstance(expected_quote_fingerprint, str) and expected_quote_fingerprint.strip():
            body["expectedQuoteFingerprint"] = expected_quote_fingerprint.strip()
        if isinstance(minimum_output_amount_raw, str) and minimum_output_amount_raw.strip():
            body["minimumTokenOutAmount"] = minimum_output_amount_raw.strip()
        data = await self.client.post("/v1/evm/uniswap/swap/send", body)
        result = dict(data.get("result") or {})
        return {
            "chain": self.chain,
            "network": self.network,
            "asset_type": "evm-uniswap-swap",
            "asset": "ERC20",
            "wallet": self.wallet_id,
            "from_address": await self.get_address(),
            "token_in": str(data.get("tokenIn") or token_in),
            "token_out": str(data.get("tokenOut") or token_out),
            "input_amount_raw": str(data.get("tokenInAmount") or amount_in_raw),
            "input_amount_ui": str(data.get("inputAmountFormatted")) if data.get("inputAmountFormatted") is not None else None,
            "estimated_output_amount_raw": str(data.get("outputAmount") or "0"),
            "estimated_output_amount_ui": str(data.get("outputAmountFormatted")) if data.get("outputAmountFormatted") is not None else None,
            "slippage_bps": int(data.get("slippageBps")) if data.get("slippageBps") is not None else None,
            "minimum_output_amount_raw": str(data.get("minimumOutputAmountRaw")) if data.get("minimumOutputAmountRaw") is not None else None,
            "swap_provider": str(data.get("protocol") or "uniswap"),
            "routing": str(data.get("routing") or "CLASSIC"),
            "quote_fingerprint": str(data.get("quoteFingerprint") or "").strip() or None,
            "router": str(data.get("router") or "").strip() or None,
            "allowance": _normalize_swap_allowance(data.get("allowance")),
            "simulation": _normalize_swap_simulation(data.get("simulation")),
            "swap_transaction": {
                "to": str((data.get("swapTransaction") or {}).get("to") or "").strip() or None,
                "value": str((data.get("swapTransaction") or {}).get("value") or "0"),
                "data_hash": str((data.get("swapTransaction") or {}).get("dataHash") or "").strip() or None,
            },
            "token_in_metadata": _normalize_token_metadata(data.get("tokenInMetadata"), token_in),
            "token_out_metadata": _normalize_token_metadata(data.get("tokenOutMetadata"), token_out),
            "hash": result.get("hash"),
            "approve_hash": result.get("approveHash"),
            "reset_allowance_hash": result.get("resetAllowanceHash"),
            "result": result,
            "chain_id": int(data.get("chainId") or 0),
            "broadcasted": True,
            "confirmed": False,
            "source": "wdk-evm-wallet",
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
    ) -> dict[str, Any]:
        resolved_address = await self.get_address()
        data = await self.client.post(
            "/v1/evm/lifi/quote",
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
                **({"slippage": slippage} if slippage is not None else {}),
                **({"allowBridges": allow_bridges} if allow_bridges is not None else {}),
                **({"denyBridges": deny_bridges} if deny_bridges is not None else {}),
                **({"preferBridges": prefer_bridges} if prefer_bridges is not None else {}),
            },
        )
        data.setdefault("address", resolved_address)
        return _normalize_lifi_cross_chain_payload(
            chain=self.chain,
            network=self.network,
            wallet_id=self.wallet_id,
            data=data,
            token_in=token_in,
            destination_chain=destination_chain,
            output_token=output_token,
            destination_address=destination_address,
            amount_in_raw=amount_in_raw,
            slippage=slippage,
            sign_only=self.sign_only,
        )

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
    ) -> dict[str, Any]:
        if self.sign_only:
            raise WalletBackendError("wdk_evm_local is configured as sign_only.")
        data = await self.client.post(
            "/v1/evm/lifi/send",
            {
                "walletId": self.wallet_id,
                "accountIndex": self.account_index,
                "network": self.network,
                "tokenIn": token_in,
                "destinationChain": destination_chain,
                "outputToken": output_token,
                "destinationAddress": destination_address,
                "tokenInAmount": amount_in_raw,
                **({"slippage": slippage} if slippage is not None else {}),
                **({"allowBridges": allow_bridges} if allow_bridges is not None else {}),
                **({"denyBridges": deny_bridges} if deny_bridges is not None else {}),
                **({"preferBridges": prefer_bridges} if prefer_bridges is not None else {}),
                **(
                    {"minimumTokenOutAmount": minimum_output_amount_raw}
                    if isinstance(minimum_output_amount_raw, str) and minimum_output_amount_raw.strip()
                    else {}
                ),
            },
        )
        result = dict(data.get("result") or {})
        data.setdefault("address", await self.get_address())
        shaped = _normalize_lifi_cross_chain_payload(
            chain=self.chain,
            network=self.network,
            wallet_id=self.wallet_id,
            data=data,
            token_in=token_in,
            destination_chain=destination_chain,
            output_token=output_token,
            destination_address=destination_address,
            amount_in_raw=amount_in_raw,
            slippage=slippage,
            sign_only=self.sign_only,
        )
        return {
            **shaped,
            "output_amount_raw": str(result.get("tokenOutAmount") or shaped.get("estimated_output_amount_raw") or "0"),
            "estimated_fee_wei": str(data.get("estimatedFeeWei") or result.get("fee") or shaped.get("estimated_fee_wei") or "0"),
            "estimated_swap_fee_wei": str(data.get("estimatedSwapFeeWei") or result.get("swapFee") or shaped.get("estimated_swap_fee_wei") or "0"),
            "estimated_approval_fee_wei": str(data.get("estimatedApprovalFeeWei") or result.get("approvalFee") or shaped.get("estimated_approval_fee_wei") or "0"),
            "hash": result.get("hash"),
            "approve_hash": result.get("approveHash"),
            "reset_allowance_hash": result.get("resetAllowanceHash"),
            "result": result,
            "broadcasted": True,
            "confirmed": False,
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
