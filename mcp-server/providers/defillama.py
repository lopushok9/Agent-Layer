"""DeFiLlama provider — unlimited, no key required.

Endpoints used:
- /protocols           → all protocol TVLs
- yields.llama.fi/pools → yield pools
- api.llama.fi/overview/fees → fees/revenue
- stablecoins.llama.fi/stablecoins → stablecoin data
"""

import logging

from config import settings
from exceptions import ProviderError
from http_client import get_client
from rate_limiter import RateLimiter

log = logging.getLogger(__name__)

_limiter = RateLimiter(max_calls=settings.rate_limit_defillama, window_seconds=60)


async def _get(url: str, params: dict | None = None) -> dict | list:
    await _limiter.acquire()
    client = get_client()
    try:
        resp = await client.get(url, params=params)
    except Exception as exc:
        raise ProviderError("defillama", f"HTTP error: {exc}") from exc

    if resp.status_code != 200:
        raise ProviderError("defillama", f"HTTP {resp.status_code}: {resp.text[:200]}")
    return resp.json()


async def fetch_yields(
    chain: str | None = None,
    min_tvl: float = 0,
    stablecoin_only: bool = False,
    limit: int = 20,
) -> list[dict]:
    """Top DeFi yield pools with optional filters."""
    url = f"{settings.defillama_yields_url}/pools"
    data = await _get(url)

    pools = data if isinstance(data, list) else data.get("data", [])
    filtered = []
    for p in pools:
        tvl = p.get("tvlUsd") or 0
        apy = p.get("apy") or 0
        if tvl < min_tvl:
            continue
        if chain and (p.get("chain", "").lower() != chain.lower()):
            continue
        if stablecoin_only and not p.get("stablecoin", False):
            continue
        if apy <= 0:
            continue
        filtered.append(p)

    # Sort by TVL descending, take top N
    filtered.sort(key=lambda x: x.get("tvlUsd", 0), reverse=True)
    filtered = filtered[:limit]

    return [
        {
            "pool": p.get("symbol", p.get("pool", "?")),
            "project": p.get("project", "?"),
            "chain": p.get("chain", "?"),
            "tvl_usd": p.get("tvlUsd", 0),
            "apy": round(p.get("apy", 0), 2),
            "apy_base": p.get("apyBase"),
            "apy_reward": p.get("apyReward"),
            "stablecoin": p.get("stablecoin", False),
            "source": "defillama",
        }
        for p in filtered
    ]


async def fetch_protocols(limit: int = 20) -> list[dict]:
    """Top protocols by TVL."""
    url = f"{settings.defillama_base_url}/protocols"
    data = await _get(url)

    if not isinstance(data, list):
        raise ProviderError("defillama", "Unexpected protocols response format")

    # Already sorted by TVL descending from API
    top = data[:limit]
    return [
        {
            "name": p.get("name", "?"),
            "tvl_usd": p.get("tvl", 0),
            "change_1d": p.get("change_1d"),
            "change_7d": p.get("change_7d"),
            "chains": p.get("chains", []),
            "category": p.get("category"),
            "source": "defillama",
        }
        for p in top
    ]


async def fetch_protocol_tvl(protocol: str) -> dict:
    """TVL for a specific protocol (by slug)."""
    url = f"{settings.defillama_base_url}/tvl/{protocol}"
    tvl = await _get(url)
    # Returns a bare number
    if isinstance(tvl, (int, float)):
        return {
            "name": protocol,
            "tvl_usd": float(tvl),
            "change_1d": None,
            "change_7d": None,
            "chains": [],
            "category": None,
            "source": "defillama",
        }
    raise ProviderError("defillama", f"Unexpected TVL response for {protocol}")


async def fetch_fees(limit: int = 20) -> list[dict]:
    """Protocol fees/revenue for last 24h."""
    url = f"{settings.defillama_base_url}/overview/fees"
    data = await _get(url)

    protocols = data.get("protocols", [])
    # Sort by total24h descending
    protocols.sort(key=lambda x: x.get("total24h") or 0, reverse=True)
    top = protocols[:limit]

    return [
        {
            "name": p.get("name", "?"),
            "fees_24h": p.get("total24h"),
            "revenue_24h": p.get("revenue24h"),
            "category": p.get("category"),
            "source": "defillama",
        }
        for p in top
    ]


async def fetch_stablecoins(limit: int = 20) -> list[dict]:
    """Stablecoin market data."""
    url = f"{settings.defillama_stablecoins_url}/stablecoins"
    data = await _get(url)

    coins = data.get("peggedAssets", [])
    # Sort by total circulating supply descending
    coins.sort(
        key=lambda x: (x.get("circulating", {}) or {}).get("peggedUSD", 0),
        reverse=True,
    )
    top = coins[:limit]

    results = []
    for c in top:
        total_circ = (c.get("circulating", {}) or {}).get("peggedUSD", 0)
        chains = c.get("chains", [])
        results.append(
            {
                "name": c.get("name", "?"),
                "symbol": c.get("symbol", "?"),
                "peg_type": c.get("pegType", "?"),
                "circulating_usd": total_circ,
                "chains": chains,
                "source": "defillama",
            }
        )
    return results
