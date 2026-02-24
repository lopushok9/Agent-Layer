"""Curve provider — free public API, no key required."""

import logging
from typing import Any

from config import settings
from exceptions import ProviderError
from http_client import get_client
from rate_limiter import RateLimiter

log = logging.getLogger(__name__)

_limiter = RateLimiter(max_calls=settings.rate_limit_curve, window_seconds=60)


def _to_float(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _extract_apy(pool: dict[str, Any]) -> tuple[float | None, float | None, float | None]:
    base = _to_float(pool.get("apyBase"))
    reward = _to_float(pool.get("apyReward"))
    total = _to_float(pool.get("apy"))

    if total is None:
        gauge_apy = pool.get("gaugeCrvApy")
        if isinstance(gauge_apy, dict):
            total = _to_float(gauge_apy.get("total"))
            if base is None:
                base = _to_float(gauge_apy.get("base"))
            if reward is None:
                reward = _to_float(gauge_apy.get("boosted"))

    if total is None and (base is not None or reward is not None):
        total = (base or 0.0) + (reward or 0.0)

    return total, base, reward


async def _get(path: str, params: dict[str, Any] | None = None) -> dict:
    await _limiter.acquire()
    client = get_client()
    url = f"{settings.curve_api_url.rstrip('/')}{path}"

    try:
        resp = await client.get(url, params=params)
    except Exception as exc:
        raise ProviderError("curve", f"HTTP error: {exc}") from exc

    if resp.status_code != 200:
        raise ProviderError("curve", f"HTTP {resp.status_code}: {resp.text[:200]}")

    data = resp.json()
    if not isinstance(data, dict):
        raise ProviderError("curve", "Unexpected response format")
    return data


async def fetch_pools(
    chain: str = "ethereum",
    registry: str = "main",
    min_tvl: float = 0,
    max_tvl: float | None = None,
    only_gauged: bool = False,
    asset_type: str | None = None,
    sort_by: str = "tvl",
    limit: int = 20,
) -> list[dict]:
    """Fetch Curve pools from a specific chain/registry."""
    payload = await _get(f"/getPools/{chain}/{registry}")
    data = payload.get("data", {})
    pools = data.get("poolData", [])

    if not isinstance(pools, list):
        raise ProviderError("curve", "Unexpected pools payload")

    wanted_asset = asset_type.lower().strip() if asset_type else None
    filtered = []

    for p in pools:
        if not isinstance(p, dict):
            continue

        tvl = _to_float(p.get("usdTotal")) or _to_float(p.get("tvl")) or 0.0
        if tvl < min_tvl:
            continue
        if max_tvl is not None and tvl > max_tvl:
            continue

        gauge_address = p.get("gaugeAddress") or p.get("gauge")
        has_gauge = bool(gauge_address)
        if only_gauged and not has_gauge:
            continue

        pool_asset_type = (p.get("assetTypeName") or p.get("assetType") or "").strip()
        if wanted_asset and pool_asset_type.lower() != wanted_asset:
            continue

        apy, apy_base, apy_reward = _extract_apy(p)

        filtered.append(
            {
                "pool": p.get("name") or p.get("symbol") or p.get("address") or "?",
                "address": p.get("address"),
                "chain": chain,
                "registry": registry,
                "asset_type": pool_asset_type or None,
                "tvl_usd": tvl,
                "apy": apy,
                "apy_base": apy_base,
                "apy_reward": apy_reward,
                "has_gauge": has_gauge,
                "gauge_address": gauge_address,
                "source": "curve",
            }
        )

    sort_keys = {
        "tvl": lambda x: x.get("tvl_usd") or 0.0,
        "apy": lambda x: x.get("apy") or 0.0,
    }
    filtered.sort(key=sort_keys.get(sort_by, sort_keys["tvl"]), reverse=True)
    return filtered[:limit]


async def fetch_subgraph_data(chain: str = "ethereum") -> dict:
    """Fetch Curve subgraph summary metrics for a chain."""
    payload = await _get(f"/getSubgraphData/{chain}")
    data = payload.get("data", {})

    if not isinstance(data, dict):
        raise ProviderError("curve", "Unexpected subgraph payload")

    tvl = _to_float(data.get("tvl")) or _to_float(data.get("totalLiquidityUSD"))
    volume_24h = _to_float(data.get("volume24h")) or _to_float(data.get("dailyVolume"))
    fees_24h = _to_float(data.get("fees24h")) or _to_float(data.get("dailyFees"))
    crv_apy = _to_float(data.get("crvApy"))
    pool_count = data.get("poolCount")
    if not isinstance(pool_count, int):
        pool_count = None

    return {
        "chain": chain,
        "tvl_usd": tvl,
        "volume_24h_usd": volume_24h,
        "fees_24h_usd": fees_24h,
        "crv_apy": crv_apy,
        "pool_count": pool_count,
        "source": "curve",
    }
