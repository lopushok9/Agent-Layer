"""DexScreener provider — free, no key required, 60 req/min.

Best source for low-cap tokens traded on DEXes (Uniswap, Raydium, PancakeSwap, etc.).
Searches across all chains and picks the pair with highest liquidity for reliable pricing.
"""

import logging

from config import settings
from exceptions import ProviderError, RateLimitError
from http_client import get_client
from rate_limiter import RateLimiter

log = logging.getLogger(__name__)

_limiter = RateLimiter(max_calls=settings.rate_limit_dexscreener, window_seconds=60)

DEXSCREENER_BASE_URL = "https://api.dexscreener.com"


async def _get(path: str, params: dict | None = None) -> dict:
    """Rate-limited GET against DexScreener."""
    await _limiter.acquire()
    url = f"{DEXSCREENER_BASE_URL}{path}"
    client = get_client()
    try:
        resp = await client.get(url, params=params)
    except Exception as exc:
        raise ProviderError("dexscreener", f"HTTP error: {exc}") from exc

    if resp.status_code == 429:
        raise RateLimitError("dexscreener")
    if resp.status_code != 200:
        raise ProviderError("dexscreener", f"HTTP {resp.status_code}: {resp.text[:200]}")
    return resp.json()


def _best_pair(pairs: list[dict], symbol: str) -> dict | None:
    """Pick the best pair for a symbol: highest USD liquidity, must have priceUsd."""
    candidates = []
    symbol_upper = symbol.upper().strip()

    for p in pairs:
        base = p.get("baseToken", {})
        # Match by base token symbol
        if base.get("symbol", "").upper() != symbol_upper:
            continue
        price = p.get("priceUsd")
        if not price:
            continue
        liquidity = (p.get("liquidity") or {}).get("usd") or 0
        candidates.append((liquidity, p))

    if not candidates:
        return None

    # Sort by liquidity descending — most liquid pair = most reliable price
    candidates.sort(key=lambda x: x[0], reverse=True)
    return candidates[0][1]


async def fetch_prices(symbols: list[str]) -> list[dict]:
    """Search DexScreener for each symbol and return price data.

    Uses the search endpoint to find tokens by ticker across all chains.
    Picks the pair with highest liquidity for each symbol.
    """
    results = []
    for symbol in symbols:
        try:
            data = await _get("/latest/dex/search", {"q": symbol.strip()})
            pairs = data.get("pairs") or []
            pair = _best_pair(pairs, symbol)
            if not pair:
                log.debug("DexScreener: no pair found for %s", symbol)
                continue

            base = pair.get("baseToken", {})
            price_change = pair.get("priceChange") or {}
            volume = pair.get("volume") or {}
            liquidity = (pair.get("liquidity") or {}).get("usd")

            results.append({
                "symbol": symbol.upper(),
                "name": base.get("name", symbol),
                "price_usd": float(pair["priceUsd"]),
                "change_24h": price_change.get("h24"),
                "volume_24h": volume.get("h24"),
                "market_cap": pair.get("marketCap") or pair.get("fdv"),
                "source": "dexscreener",
                "chain": pair.get("chainId"),
                "dex": pair.get("dexId"),
                "liquidity_usd": liquidity,
                "pair_address": pair.get("pairAddress"),
                "pair_url": pair.get("url"),
            })
        except Exception:
            log.warning("DexScreener failed for %s, skipping", symbol)

    if not results:
        raise ProviderError("dexscreener", "No prices returned")
    return results
