"""DexScreener provider for onchain token/pair discovery (price, volume, liquidity).

Public API, no key required: https://docs.dexscreener.com/api/reference. Used to
answer "which pairs exist for this token/ticker" the way app.uniswap.org's own
search box does, since the Uniswap Trading API itself only exposes quote/order/swap
for a pair you already know, not a search-by-name/address endpoint.
"""

from __future__ import annotations

import time
from typing import Any

from agent_wallet.exceptions import ProviderError
from agent_wallet.http_client import get_client

DEXSCREENER_BASE_URL = "https://api.dexscreener.com"

# DexScreener's own responses are served with `cache-control: public, max-age=30`;
# mirroring that TTL avoids redundant lookups within a session without serving
# data staler than DexScreener itself would.
_CACHE_TTL_SECONDS = 30
_CACHE_MAX_ENTRIES = 128
_cache: dict[str, tuple[float, list[dict[str, Any]]]] = {}


def _cache_get(key: str) -> list[dict[str, Any]] | None:
    entry = _cache.get(key)
    if entry is None:
        return None
    stored_at, pairs = entry
    if time.monotonic() - stored_at > _CACHE_TTL_SECONDS:
        _cache.pop(key, None)
        return None
    return pairs


def _cache_set(key: str, pairs: list[dict[str, Any]]) -> None:
    if len(_cache) >= _CACHE_MAX_ENTRIES and key not in _cache:
        oldest_key = min(_cache, key=lambda existing: _cache[existing][0])
        _cache.pop(oldest_key, None)
    _cache[key] = (time.monotonic(), pairs)


async def _get(path: str, *, params: dict[str, Any] | None = None) -> Any:
    client = get_client()
    response = await client.get(f"{DEXSCREENER_BASE_URL}{path}", params=params)
    if response.status_code != 200:
        raise ProviderError("dexscreener", f"HTTP {response.status_code}: {response.text[:300]}")
    try:
        return response.json()
    except ValueError as exc:
        raise ProviderError("dexscreener", "Unexpected non-JSON response from DexScreener.") from exc


def _extract_pairs(data: Any) -> list[dict[str, Any]]:
    if isinstance(data, dict):
        pairs = data.get("pairs")
        return pairs if isinstance(pairs, list) else []
    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict)]
    return []


async def search_pairs(query: str) -> list[dict[str, Any]]:
    """Free-text search across every chain/DEX DexScreener indexes."""
    query = query.strip()
    if not query:
        raise ProviderError("dexscreener", "query must not be empty.")
    cache_key = f"search:{query.lower()}"
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached
    data = await _get("/latest/dex/search", params={"q": query})
    pairs = _extract_pairs(data)
    _cache_set(cache_key, pairs)
    return pairs


async def get_pairs_for_token(*, chain: str, token_address: str) -> list[dict[str, Any]]:
    """All pairs for a single token address on one chain, across every DEX on it."""
    chain = chain.strip().lower()
    token_address = token_address.strip()
    if not chain:
        raise ProviderError("dexscreener", "chain must not be empty.")
    if not token_address:
        raise ProviderError("dexscreener", "token_address must not be empty.")
    cache_key = f"token:{chain}:{token_address.lower()}"
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached
    data = await _get(f"/tokens/v1/{chain}/{token_address}")
    pairs = _extract_pairs(data)
    _cache_set(cache_key, pairs)
    return pairs


def normalize_pair(pair: dict[str, Any]) -> dict[str, Any]:
    """Flatten a DexScreener pair payload into the shape handed back to the agent."""
    base_token = pair.get("baseToken") or {}
    quote_token = pair.get("quoteToken") or {}
    volume = pair.get("volume") or {}
    liquidity = pair.get("liquidity") or {}
    price_change = pair.get("priceChange") or {}
    txns = pair.get("txns") or {}
    return {
        "chain_id": pair.get("chainId"),
        "dex_id": pair.get("dexId"),
        "pair_address": pair.get("pairAddress"),
        "url": pair.get("url"),
        "labels": pair.get("labels") or [],
        "base_token": {
            "address": base_token.get("address"),
            "name": base_token.get("name"),
            "symbol": base_token.get("symbol"),
        },
        "quote_token": {
            "address": quote_token.get("address"),
            "name": quote_token.get("name"),
            "symbol": quote_token.get("symbol"),
        },
        "price_usd": pair.get("priceUsd"),
        "price_native": pair.get("priceNative"),
        "price_change_pct": {
            "m5": price_change.get("m5"),
            "h1": price_change.get("h1"),
            "h6": price_change.get("h6"),
            "h24": price_change.get("h24"),
        },
        "volume_usd": {
            "m5": volume.get("m5"),
            "h1": volume.get("h1"),
            "h6": volume.get("h6"),
            "h24": volume.get("h24"),
        },
        "txns": {
            window: {"buys": counts.get("buys"), "sells": counts.get("sells")}
            for window, counts in txns.items()
            if isinstance(counts, dict)
        },
        "liquidity_usd": liquidity.get("usd"),
        "fdv_usd": pair.get("fdv"),
        "market_cap_usd": pair.get("marketCap"),
        "pair_created_at": pair.get("pairCreatedAt"),
    }
