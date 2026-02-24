"""Curve provider — free public API, no key required."""

import asyncio
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
        elif isinstance(gauge_apy, list):
            vals = [_to_float(v) for v in gauge_apy]
            vals = [v for v in vals if v is not None]
            if vals:
                # Curve usually returns [min, max] CRV APY.
                reward = max(vals)

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
    min_apy: float = 0,
    max_apy: float | None = None,
    only_gauged: bool = False,
    asset_type: str | None = None,
    sort_by: str = "tvl",
    limit: int = 20,
) -> list[dict]:
    """Fetch Curve pools from a specific chain/registry."""
    pools_payload, volumes_payload = await asyncio.gather(
        _get(f"/getPools/{chain}/{registry}"),
        _get(f"/getVolumes/{chain}"),
    )

    data = pools_payload.get("data", {})
    pools = data.get("poolData", [])
    volume_rows = (volumes_payload.get("data", {}) or {}).get("pools", [])

    if not isinstance(pools, list):
        raise ProviderError("curve", "Unexpected pools payload")
    if not isinstance(volume_rows, list):
        volume_rows = []

    volume_by_address: dict[str, dict[str, Any]] = {}
    for row in volume_rows:
        if not isinstance(row, dict):
            continue
        addr = (row.get("address") or "").lower()
        row_type = (row.get("type") or "").lower()
        if not addr:
            continue
        volume_by_address[f"{addr}:{row_type}"] = row

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

        address = (p.get("address") or "").strip()
        address_lc = address.lower()
        volume_row = volume_by_address.get(f"{address_lc}:{registry}") or volume_by_address.get(
            f"{address_lc}:main"
        )
        base_apy = None
        if isinstance(volume_row, dict):
            daily = _to_float(volume_row.get("latestDailyApyPcent")) or _to_float(
                volume_row.get("latestDailyApy")
            )
            extra = _to_float(volume_row.get("includedApyPcentFromLsts")) or 0.0
            if daily is not None:
                base_apy = daily + extra

        apy, apy_base, apy_reward = _extract_apy(p)
        if apy_base is None:
            apy_base = base_apy

        rewards = p.get("gaugeRewards")
        if isinstance(rewards, list):
            reward_sum = 0.0
            has_reward = False
            for reward in rewards:
                if not isinstance(reward, dict):
                    continue
                reward_apy = _to_float(reward.get("apy"))
                if reward_apy is None:
                    continue
                reward_sum += reward_apy
                has_reward = True
            if has_reward:
                apy_reward = (apy_reward or 0.0) + reward_sum

        if apy is None and (apy_base is not None or apy_reward is not None):
            apy = (apy_base or 0.0) + (apy_reward or 0.0)

        if apy is not None and apy < min_apy:
            continue
        if max_apy is not None and apy is not None and apy > max_apy:
            continue

        filtered.append(
            {
                "pool": p.get("name") or p.get("symbol") or p.get("address") or "?",
                "address": address or p.get("address"),
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

    pool_list = data.get("poolList", [])
    if not isinstance(pool_list, list):
        pool_list = []

    daily_apys: list[float] = []
    weekly_apys: list[float] = []
    for item in pool_list:
        if not isinstance(item, dict):
            continue
        daily = _to_float(item.get("latestDailyApy"))
        weekly = _to_float(item.get("latestWeeklyApy"))
        if daily is not None:
            daily_apys.append(daily)
        if weekly is not None:
            weekly_apys.append(weekly)

    sane_daily_apys = [x for x in daily_apys if 0 <= x <= 10_000]
    sane_weekly_apys = [x for x in weekly_apys if 0 <= x <= 10_000]

    avg_daily_apy = (sum(sane_daily_apys) / len(sane_daily_apys)) if sane_daily_apys else None
    avg_weekly_apy = (sum(sane_weekly_apys) / len(sane_weekly_apys)) if sane_weekly_apys else None
    max_daily_apy = max(sane_daily_apys) if sane_daily_apys else None
    max_weekly_apy = max(sane_weekly_apys) if sane_weekly_apys else None

    return {
        "chain": chain,
        "tvl_usd": _to_float(data.get("tvl")) or _to_float(data.get("totalLiquidityUSD")),
        "volume_24h_usd": _to_float(data.get("totalVolume")) or _to_float(data.get("volume24h")),
        "fees_24h_usd": _to_float(data.get("fees24h")) or _to_float(data.get("dailyFees")),
        "crv_apy": None,
        "pool_count": len(pool_list),
        "crypto_share_percent": _to_float(data.get("cryptoShare")),
        "crypto_volume_24h_usd": _to_float(data.get("cryptoVolume")),
        "avg_daily_apy": avg_daily_apy,
        "avg_weekly_apy": avg_weekly_apy,
        "max_daily_apy": max_daily_apy,
        "max_weekly_apy": max_weekly_apy,
        "source": "curve",
    }
