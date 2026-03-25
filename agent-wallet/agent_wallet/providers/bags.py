"""Bags provider helpers routed through the shared provider gateway."""

from __future__ import annotations

import os
from typing import Any

from agent_wallet.config import settings
from agent_wallet.exceptions import ProviderError
from agent_wallet.http_client import get_client


def _gateway_base_url() -> str:
    base_url = os.getenv("PROVIDER_GATEWAY_URL", settings.provider_gateway_url).strip()
    if not base_url:
        raise ProviderError(
            "bags",
            "Provider gateway URL is not configured for Bags integration.",
        )
    return base_url.rstrip("/")


def _gateway_headers() -> dict[str, str]:
    headers = {"Accept": "application/json"}
    bearer = os.getenv(
        "PROVIDER_GATEWAY_BEARER_TOKEN",
        settings.provider_gateway_bearer_token,
    ).strip()
    if bearer:
        headers["Authorization"] = f"Bearer {bearer}"
    return headers


def _unwrap_gateway_payload(
    status_code: int,
    payload: Any,
    *,
    operation: str,
) -> Any:
    if isinstance(payload, dict) and payload.get("ok") is False:
        message = str(payload.get("error") or f"{operation} failed.")
        raise ProviderError("bags", f"{operation} failed via provider gateway: {message}")

    if status_code != 200:
        message = payload
        if isinstance(payload, dict):
            message = payload.get("error") or payload
        raise ProviderError("bags", f"{operation} failed via provider gateway: {message}")

    return payload


def _unwrap_bags_response(
    payload: Any,
    *,
    operation: str,
) -> Any:
    if not isinstance(payload, dict):
        raise ProviderError("bags", f"Unexpected {operation} response from provider gateway.")

    if "success" not in payload:
        return payload

    if not payload.get("success"):
        error = payload.get("error") or payload.get("message") or f"{operation} failed."
        raise ProviderError("bags", f"{operation} failed: {error}")

    return payload.get("response")


async def _gateway_get_json(
    path: str,
    *,
    params: dict[str, Any],
    operation: str,
) -> Any:
    client = get_client()
    response = await client.get(
        f"{_gateway_base_url()}{path}",
        params=params,
        headers=_gateway_headers(),
    )
    payload = response.json() if response.content else {}
    gateway_payload = _unwrap_gateway_payload(
        response.status_code,
        payload,
        operation=operation,
    )
    return _unwrap_bags_response(gateway_payload, operation=operation)


async def _gateway_post_json(
    path: str,
    *,
    body: dict[str, Any],
    operation: str,
) -> Any:
    client = get_client()
    response = await client.post(
        f"{_gateway_base_url()}{path}",
        json=body,
        headers={**_gateway_headers(), "Content-Type": "application/json"},
    )
    payload = response.json() if response.content else {}
    gateway_payload = _unwrap_gateway_payload(
        response.status_code,
        payload,
        operation=operation,
    )
    return _unwrap_bags_response(gateway_payload, operation=operation)


async def fetch_trade_quote(
    *,
    input_mint: str,
    output_mint: str,
    amount_raw: int,
    slippage_bps: int = 50,
) -> dict[str, Any]:
    """Fetch a Bags trade quote via the shared provider gateway."""
    client = get_client()
    response = await client.get(
        f"{_gateway_base_url()}/v1/bags/trade/quote",
        params={
            "inputMint": input_mint,
            "outputMint": output_mint,
            "amount": str(amount_raw),
            "slippageMode": "manual",
            "slippageBps": str(slippage_bps),
        },
        headers=_gateway_headers(),
    )
    payload = response.json() if response.content else {}
    gateway_payload = _unwrap_gateway_payload(
        response.status_code,
        payload,
        operation="Bags trade quote",
    )
    quote = _unwrap_bags_response(gateway_payload, operation="Bags trade quote")
    if not isinstance(quote, dict) or "outAmount" not in quote:
        raise ProviderError("bags", "Unexpected trade quote response from Bags.")
    return quote


async def build_swap_transaction(
    *,
    user_public_key: str,
    quote_response: dict[str, Any],
) -> dict[str, Any]:
    """Build a serialized Bags swap transaction via the shared provider gateway."""
    client = get_client()
    response = await client.post(
        f"{_gateway_base_url()}/v1/bags/trade/swap",
        json={
            "quoteResponse": quote_response,
            "userPublicKey": user_public_key,
        },
        headers={**_gateway_headers(), "Content-Type": "application/json"},
    )
    payload = response.json() if response.content else {}
    gateway_payload = _unwrap_gateway_payload(
        response.status_code,
        payload,
        operation="Bags swap transaction",
    )
    swap = _unwrap_bags_response(gateway_payload, operation="Bags swap transaction")
    if not isinstance(swap, dict) or "swapTransaction" not in swap:
        raise ProviderError("bags", "Unexpected swap transaction response from Bags.")
    return swap


async def create_token_info(payload: dict[str, Any]) -> dict[str, Any]:
    response = await _gateway_post_json(
        "/v1/bags/launch/token-info",
        body=payload,
        operation="Bags token info",
    )
    if not isinstance(response, dict):
        raise ProviderError("bags", "Unexpected token info response from Bags.")
    return response


async def create_fee_share_config(payload: dict[str, Any]) -> dict[str, Any]:
    response = await _gateway_post_json(
        "/v1/bags/launch/fee-share-config",
        body=payload,
        operation="Bags fee share config",
    )
    if not isinstance(response, dict):
        raise ProviderError("bags", "Unexpected fee share config response from Bags.")
    return response


async def create_launch_transaction(payload: dict[str, Any]) -> str:
    response = await _gateway_post_json(
        "/v1/bags/launch/transaction",
        body=payload,
        operation="Bags launch transaction",
    )
    if isinstance(response, str):
        return response
    raise ProviderError("bags", "Unexpected launch transaction response from Bags.")


async def fetch_claimable_positions(wallet: str) -> Any:
    return await _gateway_get_json(
        "/v1/bags/claim/positions",
        params={"wallet": wallet},
        operation="Bags claimable positions",
    )


async def build_claim_transactions(payload: dict[str, Any]) -> Any:
    return await _gateway_post_json(
        "/v1/bags/claim/transactions",
        body=payload,
        operation="Bags claim transactions",
    )


async def fetch_lifetime_fees(token_mint: str) -> Any:
    return await _gateway_get_json(
        "/v1/bags/fees/lifetime",
        params={"tokenMint": token_mint},
        operation="Bags lifetime fees",
    )


async def fetch_claim_stats(token_mint: str) -> Any:
    return await _gateway_get_json(
        "/v1/bags/fees/claim-stats",
        params={"tokenMint": token_mint},
        operation="Bags claim stats",
    )


async def fetch_claim_events(
    *,
    token_mint: str,
    mode: str = "offset",
    limit: int | None = None,
    offset: int | None = None,
    from_ts: int | None = None,
    to_ts: int | None = None,
) -> Any:
    params: dict[str, Any] = {"tokenMint": token_mint, "mode": mode}
    if limit is not None:
        params["limit"] = str(limit)
    if offset is not None:
        params["offset"] = str(offset)
    if from_ts is not None:
        params["from"] = str(from_ts)
    if to_ts is not None:
        params["to"] = str(to_ts)
    return await _gateway_get_json(
        "/v1/bags/fees/claim-events",
        params=params,
        operation="Bags claim events",
    )
