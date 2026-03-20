"""Jupiter providers for swap routing, prices, portfolio, and lend/earn flows."""

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


def _require_api_key(provider_name: str) -> None:
    if not settings.jupiter_api_key.strip():
        raise ProviderError(
            provider_name,
            "Jupiter API key is required for this endpoint. Set JUPITER_API_KEY first.",
        )


def _normalize_named_list_response(
    data: Any,
    *,
    key: str,
    provider_name: str,
) -> dict[str, Any]:
    if isinstance(data, list):
        return {key: data}
    if isinstance(data, dict):
        items = data.get(key)
        if isinstance(items, list):
            return data
        fallback = data.get("data")
        if isinstance(fallback, list):
            normalized = dict(data)
            normalized[key] = fallback
            return normalized
    raise ProviderError(provider_name, f"Unexpected {key} response from Jupiter.")


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


async def fetch_portfolio_platforms() -> dict[str, Any]:
    """Fetch the list of supported Jupiter Portfolio platforms."""
    client = get_client()
    response = await client.get(
        f"{settings.jupiter_portfolio_api_base_url.rstrip('/')}/platforms",
        headers=_headers(),
    )
    if response.status_code != 200:
        raise ProviderError(
            "jupiter-portfolio",
            f"HTTP {response.status_code}: {response.text[:300]}",
        )
    data = response.json()
    if not isinstance(data, dict):
        raise ProviderError("jupiter-portfolio", "Unexpected portfolio platforms response.")
    return data


async def fetch_portfolio_positions(
    *,
    address: str,
    platforms: list[str] | None = None,
) -> dict[str, Any]:
    """Fetch Jupiter Portfolio positions for a wallet address."""
    client = get_client()
    params: dict[str, str] = {"address": address}
    if platforms:
        params["platforms"] = ",".join(platforms)
    response = await client.get(
        f"{settings.jupiter_portfolio_api_base_url.rstrip('/')}/positions",
        params=params,
        headers=_headers(),
    )
    if response.status_code != 200:
        raise ProviderError(
            "jupiter-portfolio",
            f"HTTP {response.status_code}: {response.text[:300]}",
        )
    data = response.json()
    if not isinstance(data, dict):
        raise ProviderError("jupiter-portfolio", "Unexpected portfolio positions response.")
    return data


async def fetch_staked_jup(*, address: str) -> dict[str, Any]:
    """Fetch staked JUP information for a wallet address."""
    client = get_client()
    response = await client.get(
        f"{settings.jupiter_portfolio_api_base_url.rstrip('/')}/staked-jup",
        params={"address": address},
        headers=_headers(),
    )
    if response.status_code != 200:
        raise ProviderError(
            "jupiter-portfolio",
            f"HTTP {response.status_code}: {response.text[:300]}",
        )
    data = response.json()
    if not isinstance(data, dict):
        raise ProviderError("jupiter-portfolio", "Unexpected staked JUP response.")
    return data


async def fetch_earn_tokens() -> dict[str, Any]:
    """Fetch supported Jupiter Earn vault tokens."""
    _require_api_key("jupiter-lend")
    client = get_client()
    response = await client.get(
        f"{settings.jupiter_lend_api_base_url.rstrip('/')}/earn/tokens",
        headers=_headers(),
    )
    if response.status_code != 200:
        raise ProviderError("jupiter-lend", f"HTTP {response.status_code}: {response.text[:300]}")
    return _normalize_named_list_response(
        response.json(),
        key="tokens",
        provider_name="jupiter-lend",
    )


async def fetch_earn_positions(*, users: list[str]) -> dict[str, Any]:
    """Fetch Jupiter Earn positions for one or more users."""
    _require_api_key("jupiter-lend")
    client = get_client()
    response = await client.get(
        f"{settings.jupiter_lend_api_base_url.rstrip('/')}/earn/positions",
        params={"users": ",".join(users)},
        headers=_headers(),
    )
    if response.status_code != 200:
        raise ProviderError("jupiter-lend", f"HTTP {response.status_code}: {response.text[:300]}")
    return _normalize_named_list_response(
        response.json(),
        key="positions",
        provider_name="jupiter-lend",
    )


async def fetch_earn_earnings(*, user: str, positions: list[str]) -> dict[str, Any]:
    """Fetch Jupiter Earn earnings for a user and position list."""
    _require_api_key("jupiter-lend")
    client = get_client()
    response = await client.get(
        f"{settings.jupiter_lend_api_base_url.rstrip('/')}/earn/earnings",
        params={"user": user, "positions": ",".join(positions)},
        headers=_headers(),
    )
    if response.status_code != 200:
        raise ProviderError("jupiter-lend", f"HTTP {response.status_code}: {response.text[:300]}")
    return _normalize_named_list_response(
        response.json(),
        key="earnings",
        provider_name="jupiter-lend",
    )


async def build_earn_deposit_transaction(
    *,
    asset: str,
    user_address: str,
    amount_raw: str,
) -> dict[str, Any]:
    """Build an unsigned Jupiter Earn deposit transaction."""
    _require_api_key("jupiter-lend")
    client = get_client()
    response = await client.post(
        f"{settings.jupiter_lend_api_base_url.rstrip('/')}/earn/deposit",
        json={
            "asset": asset,
            "signer": user_address,
            "amount": amount_raw,
        },
        headers=_headers(),
    )
    if response.status_code != 200:
        raise ProviderError("jupiter-lend", f"HTTP {response.status_code}: {response.text[:300]}")
    data = response.json()
    if not isinstance(data, dict) or "transaction" not in data:
        raise ProviderError("jupiter-lend", "Unexpected Earn deposit response.")
    return data


async def build_earn_withdraw_transaction(
    *,
    asset: str,
    user_address: str,
    amount_raw: str,
) -> dict[str, Any]:
    """Build an unsigned Jupiter Earn withdraw transaction."""
    _require_api_key("jupiter-lend")
    client = get_client()
    response = await client.post(
        f"{settings.jupiter_lend_api_base_url.rstrip('/')}/earn/withdraw",
        json={
            "asset": asset,
            "signer": user_address,
            "amount": amount_raw,
        },
        headers=_headers(),
    )
    if response.status_code != 200:
        raise ProviderError("jupiter-lend", f"HTTP {response.status_code}: {response.text[:300]}")
    data = response.json()
    if not isinstance(data, dict) or "transaction" not in data:
        raise ProviderError("jupiter-lend", "Unexpected Earn withdraw response.")
    return data
