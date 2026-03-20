"""Kamino REST API provider for lending market data and unsigned transaction building."""

from __future__ import annotations

from typing import Any

from agent_wallet.config import settings
from agent_wallet.exceptions import ProviderError
from agent_wallet.http_client import get_client


def _normalized_api_base() -> str:
    return settings.kamino_api_base_url.rstrip("/")


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
    raise ProviderError(provider_name, f"Unexpected {key} response from Kamino.")


def _normalized_tx_response(data: Any, *, provider_name: str) -> dict[str, Any]:
    if not isinstance(data, dict) or not isinstance(data.get("transaction"), str):
        raise ProviderError(provider_name, "Unexpected transaction build response from Kamino.")
    return data


def _env_name(network: str) -> str:
    normalized = str(network).strip().lower()
    if normalized == "devnet":
        return "devnet"
    return "mainnet-beta"


async def fetch_lend_markets() -> dict[str, Any]:
    """Fetch Kamino lending markets for the configured program id."""
    client = get_client()
    response = await client.get(
        f"{_normalized_api_base()}/v2/kamino-market",
        params={"programId": settings.kamino_program_id},
    )
    if response.status_code != 200:
        raise ProviderError("kamino", f"HTTP {response.status_code}: {response.text[:300]}")
    return _normalize_named_list_response(
        response.json(),
        key="markets",
        provider_name="kamino",
    )


async def fetch_lend_market_reserves(
    *,
    market: str,
    network: str,
) -> dict[str, Any]:
    """Fetch reserve metrics for one Kamino lending market."""
    client = get_client()
    response = await client.get(
        f"{_normalized_api_base()}/kamino-market/{market}/reserves/metrics",
        params={"env": _env_name(network)},
    )
    if response.status_code != 200:
        raise ProviderError("kamino", f"HTTP {response.status_code}: {response.text[:300]}")
    return _normalize_named_list_response(
        response.json(),
        key="reserves",
        provider_name="kamino",
    )


async def fetch_lend_user_obligations(
    *,
    market: str,
    user: str,
    network: str,
) -> dict[str, Any]:
    """Fetch Kamino obligations for a wallet in a market."""
    client = get_client()
    response = await client.get(
        f"{_normalized_api_base()}/kamino-market/{market}/users/{user}/obligations",
        params={"env": _env_name(network)},
    )
    if response.status_code != 200:
        raise ProviderError("kamino", f"HTTP {response.status_code}: {response.text[:300]}")
    return _normalize_named_list_response(
        response.json(),
        key="obligations",
        provider_name="kamino",
    )


async def fetch_lend_user_rewards(*, user: str) -> dict[str, Any]:
    """Fetch Kamino rewards summary for a wallet."""
    client = get_client()
    response = await client.get(
        f"{_normalized_api_base()}/klend/users/{user}/rewards",
    )
    if response.status_code != 200:
        raise ProviderError("kamino", f"HTTP {response.status_code}: {response.text[:300]}")
    data = response.json()
    if not isinstance(data, dict):
        raise ProviderError("kamino", "Unexpected rewards response from Kamino.")
    rewards = data.get("rewards")
    if rewards is None:
        data = dict(data)
        data["rewards"] = []
    elif not isinstance(rewards, list):
        raise ProviderError("kamino", "Unexpected rewards response from Kamino.")
    return data


async def build_lend_deposit_transaction(
    *,
    wallet: str,
    market: str,
    reserve: str,
    amount_ui: str,
) -> dict[str, Any]:
    """Build an unsigned Kamino deposit transaction."""
    client = get_client()
    response = await client.post(
        f"{_normalized_api_base()}/ktx/klend/deposit",
        json={
            "wallet": wallet,
            "market": market,
            "reserve": reserve,
            "amount": amount_ui,
        },
    )
    if response.status_code != 200:
        raise ProviderError("kamino", f"HTTP {response.status_code}: {response.text[:300]}")
    return _normalized_tx_response(response.json(), provider_name="kamino")


async def build_lend_withdraw_transaction(
    *,
    wallet: str,
    market: str,
    reserve: str,
    amount_ui: str,
) -> dict[str, Any]:
    """Build an unsigned Kamino withdraw transaction."""
    client = get_client()
    response = await client.post(
        f"{_normalized_api_base()}/ktx/klend/withdraw",
        json={
            "wallet": wallet,
            "market": market,
            "reserve": reserve,
            "amount": amount_ui,
        },
    )
    if response.status_code != 200:
        raise ProviderError("kamino", f"HTTP {response.status_code}: {response.text[:300]}")
    return _normalized_tx_response(response.json(), provider_name="kamino")


async def build_lend_borrow_transaction(
    *,
    wallet: str,
    market: str,
    reserve: str,
    amount_ui: str,
) -> dict[str, Any]:
    """Build an unsigned Kamino borrow transaction."""
    client = get_client()
    response = await client.post(
        f"{_normalized_api_base()}/ktx/klend/borrow",
        json={
            "wallet": wallet,
            "market": market,
            "reserve": reserve,
            "amount": amount_ui,
        },
    )
    if response.status_code != 200:
        raise ProviderError("kamino", f"HTTP {response.status_code}: {response.text[:300]}")
    return _normalized_tx_response(response.json(), provider_name="kamino")


async def build_lend_repay_transaction(
    *,
    wallet: str,
    market: str,
    reserve: str,
    amount_ui: str,
) -> dict[str, Any]:
    """Build an unsigned Kamino repay transaction."""
    client = get_client()
    response = await client.post(
        f"{_normalized_api_base()}/ktx/klend/repay",
        json={
            "wallet": wallet,
            "market": market,
            "reserve": reserve,
            "amount": amount_ui,
        },
    )
    if response.status_code != 200:
        raise ProviderError("kamino", f"HTTP {response.status_code}: {response.text[:300]}")
    return _normalized_tx_response(response.json(), provider_name="kamino")
