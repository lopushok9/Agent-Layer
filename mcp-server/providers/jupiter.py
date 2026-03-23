"""Jupiter provider — Solana token discovery + USD prices via api.jup.ag.

Uses:
- Tokens V2 Search for symbol/name/mint resolution
- Price V3 for batch USD prices
"""

from __future__ import annotations

import logging
import re

from config import settings
from exceptions import ProviderError, RateLimitError
from http_client import get_client
from rate_limiter import RateLimiter

log = logging.getLogger(__name__)

_limiter = RateLimiter(max_calls=settings.rate_limit_jupiter, window_seconds=60)

SOLANA_MINT_RE = re.compile(r"^[1-9A-HJ-NP-Za-km-z]{32,44}$")


def is_probable_mint(value: str) -> bool:
    """Return True when the input looks like a Solana mint address."""
    return bool(SOLANA_MINT_RE.fullmatch(value.strip()))


def _auth_headers() -> dict[str, str]:
    if not settings.jupiter_api_key:
        raise ProviderError(
            "jupiter",
            "JUPITER_API_KEY not configured. Create an API key at https://portal.jup.ag.",
        )
    return {"x-api-key": settings.jupiter_api_key}


async def _get(path: str, params: dict | None = None) -> dict | list:
    await _limiter.acquire()
    url = f"{settings.jupiter_api_url.rstrip('/')}{path}"
    client = get_client()
    try:
        resp = await client.get(url, params=params, headers=_auth_headers())
    except Exception as exc:
        raise ProviderError("jupiter", f"HTTP error: {exc}") from exc

    if resp.status_code == 401:
        raise ProviderError("jupiter", "Invalid API key")
    if resp.status_code == 429:
        raise RateLimitError("jupiter")
    if resp.status_code != 200:
        raise ProviderError("jupiter", f"HTTP {resp.status_code}: {resp.text[:200]}")
    return resp.json()


def _safe_float(value: object) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _token_score(token: dict, query: str) -> float:
    """Rank search results for one user query."""
    score = 0.0
    query_stripped = query.strip()
    query_lower = query_stripped.lower()
    query_upper = query_stripped.upper()

    token_id = str(token.get("id", "")).strip()
    symbol = str(token.get("symbol", "")).strip()
    name = str(token.get("name", "")).strip()

    if token_id == query_stripped:
        score += 10_000
    if symbol.upper() == query_upper:
        score += 1_000
    elif symbol.upper().startswith(query_upper):
        score += 250
    if name.lower() == query_lower:
        score += 200

    if token.get("isVerified"):
        score += 250

    organic_score = _safe_float(token.get("organicScore")) or 0.0
    liquidity = _safe_float(token.get("liquidity")) or 0.0
    market_cap = _safe_float(token.get("mcap")) or 0.0

    score += organic_score
    score += min(liquidity / 50_000, 100)
    score += min(market_cap / 1_000_000, 100)
    return score


def _pick_best_token(tokens: list[dict], query: str) -> dict | None:
    if not tokens:
        return None

    query_stripped = query.strip()
    if is_probable_mint(query_stripped):
        for token in tokens:
            if str(token.get("id", "")).strip() == query_stripped:
                return token

    return max(tokens, key=lambda token: _token_score(token, query_stripped))


async def _search_token(query: str) -> dict | None:
    payload = await _get("/tokens/v2/search", {"query": query.strip()})
    if not isinstance(payload, list):
        raise ProviderError("jupiter", "Unexpected token search response format")
    rows = [row for row in payload if isinstance(row, dict)]
    return _pick_best_token(rows, query)


async def _search_mint_batch(mints: list[str]) -> dict[str, dict]:
    if not mints:
        return {}

    payload = await _get("/tokens/v2/search", {"query": ",".join(mints)})
    if not isinstance(payload, list):
        raise ProviderError("jupiter", "Unexpected token search response format")

    by_mint: dict[str, dict] = {}
    for row in payload:
        if not isinstance(row, dict):
            continue
        mint = str(row.get("id", "")).strip()
        if mint:
            by_mint[mint] = row
    return by_mint


async def _resolve_assets(assets: list[str]) -> list[dict]:
    mint_assets = [asset.strip() for asset in assets if is_probable_mint(asset)]

    mint_index: dict[str, dict] = {}
    for start in range(0, len(mint_assets), 100):
        mint_index.update(await _search_mint_batch(mint_assets[start : start + 100]))

    resolved: list[dict] = []
    for asset in assets:
        asset_stripped = asset.strip()
        token = None
        if is_probable_mint(asset_stripped):
            token = mint_index.get(asset_stripped)
        else:
            token = await _search_token(asset_stripped)

        if token is None:
            log.info("Jupiter could not resolve asset: %s", asset_stripped)
            continue

        resolved.append({"asset_id": asset_stripped, "token": token})

    return resolved


async def _fetch_price_batch(mints: list[str]) -> dict[str, dict]:
    if not mints:
        return {}

    payload = await _get("/price/v3", {"ids": ",".join(mints)})
    if not isinstance(payload, dict):
        raise ProviderError("jupiter", "Unexpected price response format")

    return {
        mint: item
        for mint, item in payload.items()
        if isinstance(mint, str) and isinstance(item, dict)
    }


async def fetch_prices(assets: list[str]) -> list[dict]:
    """Resolve Solana assets and return Jupiter price data."""
    cleaned = [asset.strip() for asset in assets if asset and asset.strip()]
    if not cleaned:
        return []

    resolved = await _resolve_assets(cleaned)
    if not resolved:
        raise ProviderError("jupiter", "No Solana assets resolved")

    unique_mints: list[str] = []
    seen: set[str] = set()
    for item in resolved:
        mint = str(item["token"].get("id", "")).strip()
        if mint and mint not in seen:
            seen.add(mint)
            unique_mints.append(mint)

    price_index: dict[str, dict] = {}
    for start in range(0, len(unique_mints), 50):
        price_index.update(await _fetch_price_batch(unique_mints[start : start + 50]))

    results: list[dict] = []
    for item in resolved:
        token = item["token"]
        mint = str(token.get("id", "")).strip()
        price_item = price_index.get(mint)
        if not price_item:
            continue

        stats_24h = token.get("stats24h") or {}
        buy_volume = _safe_float(stats_24h.get("buyVolume")) or 0.0
        sell_volume = _safe_float(stats_24h.get("sellVolume")) or 0.0
        volume_24h = buy_volume + sell_volume

        results.append(
            {
                "asset_id": item["asset_id"],
                "mint": mint,
                "symbol": str(token.get("symbol") or item["asset_id"]).upper(),
                "name": str(token.get("name") or token.get("symbol") or item["asset_id"]),
                "price_usd": _safe_float(price_item.get("usdPrice")) or 0.0,
                "change_24h": _safe_float(price_item.get("priceChange24h"))
                or _safe_float(stats_24h.get("priceChange")),
                "volume_24h": volume_24h or None,
                "market_cap": _safe_float(token.get("mcap")),
                "decimals": token.get("decimals"),
                "block_id": price_item.get("blockId") or token.get("priceBlockId"),
                "liquidity_usd": _safe_float(token.get("liquidity")),
                "verified": token.get("isVerified"),
                "organic_score": _safe_float(token.get("organicScore")),
                "source": "jupiter",
            }
        )

    if not results:
        raise ProviderError("jupiter", "No prices returned")

    return results
