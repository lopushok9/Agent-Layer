"""CoinCap provider — unlimited, no key required. Used as fallback for prices."""

import logging

from config import settings
from exceptions import ProviderError
from http_client import get_client
from rate_limiter import RateLimiter

log = logging.getLogger(__name__)

_limiter = RateLimiter(max_calls=settings.rate_limit_coincap, window_seconds=60)

# CoinCap uses its own ID scheme (lowercase, hyphenated).
TICKER_MAP: dict[str, str] = {
    "BTC": "bitcoin",
    "ETH": "ethereum",
    "SOL": "solana",
    "BNB": "binance-coin",
    "XRP": "xrp",
    "ADA": "cardano",
    "DOGE": "dogecoin",
    "AVAX": "avalanche",
    "DOT": "polkadot",
    "MATIC": "polygon",
    "POL": "polygon",
    "LINK": "chainlink",
    "UNI": "uniswap",
    "AAVE": "aave",
    "ATOM": "cosmos",
    "NEAR": "near-protocol",
    "LTC": "litecoin",
    "BCH": "bitcoin-cash",
    "TRX": "tron",
    "SHIB": "shiba-inu",
    "USDT": "tether",
    "USDC": "usd-coin",
    "DAI": "multi-collateral-dai",
    "TON": "toncoin",
}


def resolve_id(symbol: str) -> str:
    upper = symbol.upper().strip()
    if upper in TICKER_MAP:
        return TICKER_MAP[upper]
    return symbol.lower().strip()


async def _get(path: str, params: dict | None = None) -> dict:
    await _limiter.acquire()
    url = f"{settings.coincap_api_url}{path}"
    client = get_client()
    try:
        resp = await client.get(url, params=params)
    except Exception as exc:
        raise ProviderError("coincap", f"HTTP error: {exc}") from exc

    if resp.status_code != 200:
        raise ProviderError("coincap", f"HTTP {resp.status_code}: {resp.text[:200]}")
    return resp.json()


async def fetch_prices(symbols: list[str]) -> list[dict]:
    """Fetch prices one-by-one from CoinCap (no batch endpoint)."""
    results = []
    for symbol in symbols:
        cc_id = resolve_id(symbol)
        try:
            data = await _get(f"/assets/{cc_id}")
            asset = data.get("data", {})
            price = float(asset.get("priceUsd", 0))
            change = float(asset.get("changePercent24Hr", 0)) if asset.get("changePercent24Hr") else None
            volume = float(asset.get("volumeUsd24Hr", 0)) if asset.get("volumeUsd24Hr") else None
            mcap = float(asset.get("marketCapUsd", 0)) if asset.get("marketCapUsd") else None
            results.append(
                {
                    "symbol": symbol.upper(),
                    "name": asset.get("name", cc_id),
                    "price_usd": price,
                    "change_24h": change,
                    "volume_24h": volume,
                    "market_cap": mcap,
                    "source": "coincap",
                }
            )
        except Exception:
            log.warning("CoinCap failed for %s, skipping", symbol)
    if not results:
        raise ProviderError("coincap", "No prices returned")
    return results
