"""Jupiter providers for swap routing and price flows."""

from __future__ import annotations

import json
import os
from typing import Any

from agent_wallet.config import settings
from agent_wallet.exceptions import ProviderError
from agent_wallet.http_client import get_client

JUPITER_SWAP_FALLBACK_PRIORITY_MAX_LAMPORTS = 2_000_000


def _headers() -> dict[str, str]:
    headers = {"Accept": "application/json"}
    if settings.jupiter_api_key.strip():
        headers["x-api-key"] = settings.jupiter_api_key.strip()
    return headers


def _gateway_base_url() -> str:
    return os.getenv("PROVIDER_GATEWAY_URL", settings.provider_gateway_url).strip().rstrip("/")


def _gateway_headers() -> dict[str, str]:
    headers = {"Accept": "application/json"}
    bearer = os.getenv(
        "PROVIDER_GATEWAY_BEARER_TOKEN",
        settings.provider_gateway_bearer_token,
    ).strip()
    if bearer:
        headers["Authorization"] = f"Bearer {bearer}"
    return headers


def _gateway_enabled() -> bool:
    return bool(_gateway_base_url())


async def _gateway_get(path_suffix: str, *, params: dict[str, Any] | None = None) -> tuple[int, Any]:
    """Make a GET request through provider gateway."""
    client = get_client()
    response = await client.get(
        f"{_gateway_base_url()}/v1/jupiter/swap/{path_suffix}",
        params=params,
        headers=_gateway_headers(),
    )
    if not response.content:
        return response.status_code, {}
    try:
        return response.status_code, response.json()
    except ValueError:
        return response.status_code, response.text[:500]


async def _gateway_post(path_suffix: str, *, body: dict[str, Any]) -> tuple[int, Any]:
    """Make a POST request through provider gateway."""
    client = get_client()
    response = await client.post(
        f"{_gateway_base_url()}/v1/jupiter/swap/{path_suffix}",
        json=body,
        headers={**_gateway_headers(), "Content-Type": "application/json"},
    )
    if not response.content:
        return response.status_code, {}
    try:
        return response.status_code, response.json()
    except ValueError:
        return response.status_code, response.text[:500]


def _direct_jupiter_enabled() -> bool:
    return bool(settings.jupiter_api_key.strip())


def _swap_fallback_prioritization_fee() -> dict[str, Any]:
    return {
        "priorityLevelWithMaxLamports": {
            "priorityLevel": "veryHigh",
            "maxLamports": JUPITER_SWAP_FALLBACK_PRIORITY_MAX_LAMPORTS,
            "global": False,
        }
    }


def _swap_fallback_build_body(
    *,
    user_public_key: str,
    quote_response: dict[str, Any],
    wrap_and_unwrap_sol: bool,
) -> dict[str, Any]:
    return {
        "userPublicKey": user_public_key,
        "quoteResponse": quote_response,
        "wrapAndUnwrapSol": wrap_and_unwrap_sol,
        "dynamicComputeUnitLimit": True,
        "dynamicSlippage": True,
        "prioritizationFeeLamports": _swap_fallback_prioritization_fee(),
    }


def _swap_v2_base_url() -> str:
    return os.getenv(
        "JUPITER_SWAP_V2_API_BASE_URL",
        settings.jupiter_swap_v2_api_base_url,
    ).strip().rstrip("/")


async def fetch_quote(
    *,
    input_mint: str,
    output_mint: str,
    amount_raw: int,
    slippage_bps: int = 50,
    restrict_intermediate_tokens: bool = True,
    only_direct_routes: bool = False,
    swap_mode: str = "ExactIn",
    exclude_dexes: list[str] | None = None,
) -> dict[str, Any]:
    """Fetch a Jupiter quote for an exact-in swap.

    Tries direct Jupiter API first. On free-tier errors (TOKEN_NOT_TRADABLE,
    NOT_SUPPORTED) falls back to provider gateway when configured.
    """
    # Try direct first
    try:
        return await _fetch_quote_direct(
            input_mint=input_mint,
            output_mint=output_mint,
            amount_raw=amount_raw,
            slippage_bps=slippage_bps,
            restrict_intermediate_tokens=restrict_intermediate_tokens,
            only_direct_routes=only_direct_routes,
            swap_mode=swap_mode,
            exclude_dexes=exclude_dexes,
        )
    except ProviderError as exc:
        error_msg = str(exc).lower()
        # Only fall back for known free-tier limitations
        gateway_fallback_errors = (
            "not tradable",
            "token_not_tradable",
            "not supported",
            "restrict_intermediate_tokens",
        )
        if not any(phrase in error_msg for phrase in gateway_fallback_errors):
            raise
        if not _gateway_enabled():
            raise
        # Retry via gateway with relaxed restrictions
        return await _fetch_quote_via_gateway(
            input_mint=input_mint,
            output_mint=output_mint,
            amount_raw=amount_raw,
            slippage_bps=slippage_bps,
            restrict_intermediate_tokens=False,
            only_direct_routes=only_direct_routes,
            swap_mode=swap_mode,
        )


async def _fetch_quote_direct(
    *,
    input_mint: str,
    output_mint: str,
    amount_raw: int,
    slippage_bps: int = 50,
    restrict_intermediate_tokens: bool = True,
    only_direct_routes: bool = False,
    swap_mode: str = "ExactIn",
    exclude_dexes: list[str] | None = None,
) -> dict[str, Any]:
    """Fetch a Jupiter quote directly from Jupiter API."""
    client = get_client()
    params = {
        "inputMint": input_mint,
        "outputMint": output_mint,
        "amount": str(amount_raw),
        "slippageBps": str(slippage_bps),
        "swapMode": swap_mode,
        "restrictIntermediateTokens": str(restrict_intermediate_tokens).lower(),
        "onlyDirectRoutes": str(only_direct_routes).lower(),
    }
    if exclude_dexes:
        params["excludeDexes"] = ",".join(str(d).strip() for d in exclude_dexes if str(d).strip())
    response = await client.get(
        f"{settings.jupiter_api_base_url.rstrip('/')}/quote",
        params=params,
        headers=_headers(),
    )
    if response.status_code != 200:
        raise ProviderError("jupiter", f"HTTP {response.status_code}: {response.text[:300]}")
    data = response.json()
    if not isinstance(data, dict) or "outAmount" not in data:
        raise ProviderError("jupiter", "Unexpected quote response from Jupiter.")
    return data


async def _fetch_quote_via_gateway(
    *,
    input_mint: str,
    output_mint: str,
    amount_raw: int,
    slippage_bps: int = 50,
    restrict_intermediate_tokens: bool = False,
    only_direct_routes: bool = False,
    swap_mode: str = "ExactIn",
) -> dict[str, Any]:
    """Fetch a Jupiter quote via provider gateway (uses API key)."""
    params: dict[str, Any] = {
        "inputMint": input_mint,
        "outputMint": output_mint,
        "amount": str(amount_raw),
        "slippageBps": str(slippage_bps),
        "swapMode": swap_mode,
    }
    if only_direct_routes:
        params["onlyDirectRoutes"] = "true"

    status_code, payload = await _gateway_get("quote", params=params)
    if status_code != 200:
        error_msg = payload if isinstance(payload, str) else json.dumps(payload)
        raise ProviderError("jupiter-gateway", f"HTTP {status_code}: {error_msg}")
    if isinstance(payload, dict) and payload.get("errorCode"):
        raise ProviderError("jupiter-gateway", str(payload.get("error") or payload.get("errorCode")))
    if not isinstance(payload, dict) or "outAmount" not in payload:
        raise ProviderError("jupiter-gateway", "Unexpected quote response from gateway.")
    return payload


async def fetch_ultra_order(
    *,
    input_mint: str,
    output_mint: str,
    amount_raw: int,
    taker: str | None = None,
    slippage_bps: int = 50,
    swap_mode: str = "ExactIn",
) -> dict[str, Any]:
    """Fetch a Jupiter Ultra order for an exact-in swap."""
    client = get_client()
    params = {
        "inputMint": input_mint,
        "outputMint": output_mint,
        "amount": str(amount_raw),
        "swapMode": swap_mode,
        "slippageBps": str(slippage_bps),
    }
    if taker:
        params["taker"] = taker
    response = await client.get(
        f"{settings.jupiter_ultra_api_base_url.rstrip('/')}/order",
        params=params,
        headers=_headers(),
    )
    if response.status_code != 200:
        raise ProviderError("jupiter-ultra", f"HTTP {response.status_code}: {response.text[:300]}")
    data = response.json()
    if not isinstance(data, dict):
        raise ProviderError("jupiter-ultra", "Unexpected order response from Jupiter Ultra.")
    if data.get("error") or data.get("errorCode"):
        raise ProviderError(
            "jupiter-ultra",
            str(data.get("error") or data.get("errorCode") or "Unknown Ultra error."),
        )
    if "outAmount" not in data:
        raise ProviderError("jupiter-ultra", "Unexpected order response from Jupiter Ultra.")
    return data


async def fetch_swap_v2_order(
    *,
    input_mint: str,
    output_mint: str,
    amount_raw: int,
    taker: str,
    slippage_bps: int | str | None = None,
    exclude_routers: list[str] | None = None,
    swap_mode: str = "ExactIn",
) -> dict[str, Any]:
    """Fetch a Jupiter Swap API V2 meta-aggregator order."""
    client = get_client()
    params: dict[str, Any] = {
        "inputMint": input_mint,
        "outputMint": output_mint,
        "amount": str(amount_raw),
        "taker": taker,
    }
    if swap_mode != "ExactIn":
        params["swapMode"] = swap_mode
    if slippage_bps is not None:
        params["slippageBps"] = str(slippage_bps)
    if exclude_routers:
        params["excludeRouters"] = ",".join(str(item).strip() for item in exclude_routers if str(item).strip())

    response = await client.get(
        f"{_swap_v2_base_url()}/order",
        params=params,
        headers=_headers(),
    )
    if response.status_code != 200:
        raise ProviderError("jupiter-v2", f"HTTP {response.status_code}: {response.text[:300]}")
    data = response.json()
    if not isinstance(data, dict):
        raise ProviderError("jupiter-v2", "Unexpected order response from Jupiter Swap V2.")
    if data.get("error") or data.get("errorCode"):
        raise ProviderError(
            "jupiter-v2",
            str(data.get("error") or data.get("errorCode") or "Unknown Swap V2 order error."),
            details=data,
        )
    if "outAmount" not in data:
        raise ProviderError("jupiter-v2", "Unexpected order response from Jupiter Swap V2.")
    return data


async def build_swap_transaction(
    *,
    user_public_key: str,
    quote_response: dict[str, Any],
    wrap_and_unwrap_sol: bool = True,
) -> dict[str, Any]:
    """Build a serialized swap transaction from a Jupiter quote.

    Tries direct Jupiter API first. Falls back to provider gateway on error.
    """
    # Try direct first
    try:
        return await _build_swap_direct(
            user_public_key=user_public_key,
            quote_response=quote_response,
            wrap_and_unwrap_sol=wrap_and_unwrap_sol,
        )
    except ProviderError as exc:
        if not _gateway_enabled():
            raise
        # Fall back to gateway
        return await _build_swap_via_gateway(
            user_public_key=user_public_key,
            quote_response=quote_response,
            wrap_and_unwrap_sol=wrap_and_unwrap_sol,
        )


async def _build_swap_direct(
    *,
    user_public_key: str,
    quote_response: dict[str, Any],
    wrap_and_unwrap_sol: bool = True,
) -> dict[str, Any]:
    """Build a swap transaction directly via Jupiter API."""
    client = get_client()
    body = _swap_fallback_build_body(
        user_public_key=user_public_key,
        quote_response=quote_response,
        wrap_and_unwrap_sol=wrap_and_unwrap_sol,
    )
    response = await client.post(
        f"{settings.jupiter_api_base_url.rstrip('/')}/swap",
        json=body,
        headers=_headers(),
    )
    if response.status_code != 200:
        raise ProviderError("jupiter", f"HTTP {response.status_code}: {response.text[:300]}")
    data = response.json()
    if not isinstance(data, dict) or "swapTransaction" not in data:
        raise ProviderError("jupiter", "Unexpected swap response from Jupiter.")
    return data


async def _build_swap_via_gateway(
    *,
    user_public_key: str,
    quote_response: dict[str, Any],
    wrap_and_unwrap_sol: bool = True,
) -> dict[str, Any]:
    """Build a swap transaction via provider gateway (uses API key)."""
    body = _swap_fallback_build_body(
        user_public_key=user_public_key,
        quote_response=quote_response,
        wrap_and_unwrap_sol=wrap_and_unwrap_sol,
    )
    status_code, payload = await _gateway_post("swap", body=body)
    if status_code != 200:
        error_msg = payload if isinstance(payload, str) else json.dumps(payload)
        raise ProviderError("jupiter-gateway", f"HTTP {status_code}: {error_msg}")
    if isinstance(payload, dict) and payload.get("errorCode"):
        raise ProviderError("jupiter-gateway", str(payload.get("error") or payload.get("errorCode")))
    if not isinstance(payload, dict) or "swapTransaction" not in payload:
        raise ProviderError("jupiter-gateway", "Unexpected swap response from gateway.")
    return payload


async def execute_ultra_order(
    *,
    signed_transaction_base64: str,
    request_id: str,
) -> dict[str, Any]:
    """Execute a signed Jupiter Ultra order."""
    client = get_client()
    body = {
        "signedTransaction": signed_transaction_base64,
        "requestId": request_id,
    }
    response = await client.post(
        f"{settings.jupiter_ultra_api_base_url.rstrip('/')}/execute",
        json=body,
        headers=_headers(),
    )
    if response.status_code != 200:
        raise ProviderError("jupiter-ultra", f"HTTP {response.status_code}: {response.text[:300]}")
    data = response.json()
    if not isinstance(data, dict):
        raise ProviderError("jupiter-ultra", "Unexpected execute response from Jupiter Ultra.")
    if data.get("error") or data.get("errorCode"):
        raise ProviderError(
            "jupiter-ultra",
            str(data.get("error") or data.get("errorCode") or "Unknown Ultra execute error."),
        )
    return data


async def execute_swap_v2_order(
    *,
    signed_transaction_base64: str,
    request_id: str,
    last_valid_block_height: int | str | None = None,
) -> dict[str, Any]:
    """Execute a signed Jupiter Swap API V2 order."""
    client = get_client()
    body: dict[str, Any] = {
        "signedTransaction": signed_transaction_base64,
        "requestId": request_id,
    }
    if last_valid_block_height is not None:
        body["lastValidBlockHeight"] = str(last_valid_block_height)
    response = await client.post(
        f"{_swap_v2_base_url()}/execute",
        json=body,
        headers={**_headers(), "Content-Type": "application/json"},
    )
    if response.status_code != 200:
        raise ProviderError("jupiter-v2", f"HTTP {response.status_code}: {response.text[:300]}")
    data = response.json()
    if not isinstance(data, dict):
        raise ProviderError("jupiter-v2", "Unexpected execute response from Jupiter Swap V2.")
    if data.get("error") or data.get("errorCode"):
        raise ProviderError(
            "jupiter-v2",
            str(data.get("error") or data.get("errorCode") or "Unknown Swap V2 execute error."),
            details=data,
        )
    if str(data.get("status") or "").strip().lower() == "failed":
        message = data.get("error") or data.get("code") or "Swap V2 execute failed."
        raise ProviderError("jupiter-v2", str(message), details=data)
    return data


async def fetch_prices(
    *,
    mints: list[str],
    show_extra_info: bool = False,
) -> dict[str, Any]:
    """Fetch token prices from Jupiter Price API V3."""
    if not mints:
        raise ProviderError("jupiter", "At least one mint is required for price lookup.")
    client = get_client()
    params = {
        "ids": ",".join(mints),
    }
    if show_extra_info:
        params["showExtraInfo"] = "true"
    response = await client.get(
        settings.jupiter_price_api_base_url,
        params=params,
        headers=_headers(),
    )
    if response.status_code != 200:
        raise ProviderError("jupiter", f"HTTP {response.status_code}: {response.text[:300]}")
    data = response.json()
    if not isinstance(data, dict):
        raise ProviderError("jupiter", "Unexpected price response from Jupiter.")
    return data


async def fetch_token_metadata(*, mints: list[str]) -> dict[str, dict[str, Any]]:
    """Look up token symbol/name for a batch of mints via Jupiter's token
    search API. Keyed by mint address; mints Jupiter doesn't index (very new
    or illiquid tokens) are simply absent from the result rather than
    raising, since this is display-only enrichment on top of the price data.
    """
    if not mints:
        return {}
    client = get_client()
    params = {"query": ",".join(mints)}
    response = await client.get(
        f"{settings.jupiter_token_search_api_base_url.rstrip('/')}/search",
        params=params,
        headers=_headers(),
    )
    if response.status_code != 200:
        raise ProviderError("jupiter", f"HTTP {response.status_code}: {response.text[:300]}")
    data = response.json()
    if not isinstance(data, list):
        raise ProviderError("jupiter", "Unexpected token search response from Jupiter.")
    result: dict[str, dict[str, Any]] = {}
    for item in data:
        if not isinstance(item, dict):
            continue
        mint = str(item.get("id") or "").strip()
        if not mint:
            continue
        result[mint] = {
            "symbol": item.get("symbol"),
            "name": item.get("name"),
        }
    return result
