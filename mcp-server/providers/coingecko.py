"""CoinGecko provider — free demo API, 30 req/min, no key required."""

import logging

from config import settings
from exceptions import ProviderError, RateLimitError
from http_client import get_client
from rate_limiter import RateLimiter

log = logging.getLogger(__name__)

_limiter = RateLimiter(max_calls=settings.rate_limit_coingecko, window_seconds=60)

# Maps common tickers to CoinGecko IDs.
# Extend as needed — CoinGecko requires its own slug-style IDs.
TICKER_MAP: dict[str, str] = {
    "BTC": "bitcoin",
    "ETH": "ethereum",
    "SOL": "solana",
    "BNB": "binancecoin",
    "XRP": "ripple",
    "ADA": "cardano",
    "DOGE": "dogecoin",
    "AVAX": "avalanche-2",
    "DOT": "polkadot",
    "MATIC": "matic-network",
    "POL": "matic-network",
    "LINK": "chainlink",
    "UNI": "uniswap",
    "AAVE": "aave",
    "ARB": "arbitrum",
    "OP": "optimism",
    "ATOM": "cosmos",
    "NEAR": "near",
    "APT": "aptos",
    "SUI": "sui",
    "FTM": "fantom",
    "TRX": "tron",
    "SHIB": "shiba-inu",
    "LTC": "litecoin",
    "BCH": "bitcoin-cash",
    "FIL": "filecoin",
    "IMX": "immutable-x",
    "RENDER": "render-token",
    "INJ": "injective-protocol",
    "TIA": "celestia",
    "SEI": "sei-network",
    "STX": "blockstack",
    "PEPE": "pepe",
    "WIF": "dogwifcoin",
    "USDT": "tether",
    "USDC": "usd-coin",
    "DAI": "dai",
    "STETH": "staked-ether",
    "WBTC": "wrapped-bitcoin",
    "TON": "the-open-network",
    "MKR": "maker",
    "CRV": "curve-dao-token",
    "LDO": "lido-dao",
    "RETH": "rocket-pool-eth",
}


def resolve_id(symbol: str) -> str:
    """Resolve a ticker or CoinGecko ID to a CoinGecko ID."""
    upper = symbol.upper().strip()
    if upper in TICKER_MAP:
        return TICKER_MAP[upper]
    # assume the user passed a coingecko id directly (e.g. "bitcoin")
    return symbol.lower().strip()


async def _get(path: str, params: dict | None = None) -> dict:
    """Rate-limited GET against CoinGecko."""
    await _limiter.acquire()
    url = f"{settings.coingecko_api_url}{path}"
    client = get_client()
    try:
        resp = await client.get(url, params=params)
    except Exception as exc:
        raise ProviderError("coingecko", f"HTTP error: {exc}") from exc

    if resp.status_code == 429:
        raise RateLimitError("coingecko")
    if resp.status_code != 200:
        raise ProviderError("coingecko", f"HTTP {resp.status_code}: {resp.text[:200]}")
    return resp.json()


async def fetch_prices(symbols: list[str]) -> list[dict]:
    """Fetch prices for a list of symbols/IDs. Returns raw dicts."""
    ids = [resolve_id(s) for s in symbols]
    data = await _get(
        "/simple/price",
        {
            "ids": ",".join(ids),
            "vs_currencies": "usd",
            "include_24hr_change": "true",
            "include_24hr_vol": "true",
            "include_market_cap": "true",
        },
    )
    results = []
    for symbol, cg_id in zip(symbols, ids):
        info = data.get(cg_id, {})
        if not info:
            continue
        results.append(
            {
                "symbol": symbol.upper(),
                "name": cg_id,
                "price_usd": info.get("usd", 0),
                "change_24h": info.get("usd_24h_change"),
                "volume_24h": info.get("usd_24h_vol"),
                "market_cap": info.get("usd_market_cap"),
                "source": "coingecko",
            }
        )
    return results


async def fetch_market_overview() -> dict:
    """Global market data."""
    data = await _get("/global")
    gd = data.get("data", {})
    total_mcap = gd.get("total_market_cap", {})
    total_vol = gd.get("total_volume", {})
    dominance = gd.get("market_cap_percentage", {})
    return {
        "total_market_cap_usd": total_mcap.get("usd", 0),
        "total_volume_24h_usd": total_vol.get("usd", 0),
        "btc_dominance": round(dominance.get("btc", 0), 2),
        "eth_dominance": round(dominance.get("eth", 0), 2),
        "active_cryptocurrencies": gd.get("active_cryptocurrencies", 0),
        "source": "coingecko",
    }


async def fetch_trending() -> list[dict]:
    """Trending coins in the last 24h."""
    data = await _get("/search/trending")
    results = []
    for item in data.get("coins", []):
        coin = item.get("item", {})
        results.append(
            {
                "symbol": coin.get("symbol", "").upper(),
                "name": coin.get("name", ""),
                "market_cap_rank": coin.get("market_cap_rank"),
                "price_usd": coin.get("data", {}).get("price"),
                "change_24h": coin.get("data", {}).get("price_change_percentage_24h", {}).get("usd"),
                "source": "coingecko",
            }
        )
    return results
