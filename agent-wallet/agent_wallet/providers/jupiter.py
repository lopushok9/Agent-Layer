"""Minimal Jupiter swap provider for Solana token routing."""

from __future__ import annotations

from typing import Any

from agent_wallet.config import settings
from agent_wallet.exceptions import ProviderError
from agent_wallet.http_client import get_client


def _headers() -> dict[str, str]:
    headers = {"Accept": "application/json"}
    if settings.jupiter_api_key.strip():
        headers["x-api-key"] = settings.jupiter_api_key.strip()
    return headers


async def fetch_quote(
    *,
    input_mint: str,
    output_mint: str,
    amount_raw: int,
    slippage_bps: int = 50,
    restrict_intermediate_tokens: bool = True,
    only_direct_routes: bool = False,
    swap_mode: str = "ExactIn",
) -> dict[str, Any]:
    """Fetch a Jupiter quote for an exact-in swap."""
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


async def build_swap_transaction(
    *,
    user_public_key: str,
    quote_response: dict[str, Any],
    wrap_and_unwrap_sol: bool = True,
) -> dict[str, Any]:
    """Build a serialized swap transaction from a Jupiter quote."""
    client = get_client()
    body = {
        "userPublicKey": user_public_key,
        "quoteResponse": quote_response,
        "wrapAndUnwrapSol": wrap_and_unwrap_sol,
        "dynamicComputeUnitLimit": True,
        "prioritizationFeeLamports": "auto",
    }
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
