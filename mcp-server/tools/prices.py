"""Price-related MCP tools."""

import json
import logging

from cache import Cache
from config import settings
from exceptions import AllProvidersFailedError
from models import MarketOverview, PriceData, TrendingCoin
from providers import coingecko

log = logging.getLogger(__name__)

# Lazy import to avoid circular deps — coincap loaded on demand
_coincap = None


def _get_coincap():
    global _coincap
    if _coincap is None:
        from providers import coincap

        _coincap = coincap
    return _coincap


def register(mcp, cache: Cache):
    """Register price tools on the FastMCP server."""

    @mcp.tool()
    async def get_crypto_prices(symbols: list[str]) -> str:
        """Get current prices for cryptocurrencies.

        Args:
            symbols: List of ticker symbols or CoinGecko IDs, e.g. ["BTC", "ETH", "SOL"].
                     Supports up to 50 symbols per request.

        Returns:
            JSON array with price_usd, change_24h (%), volume_24h, market_cap for each symbol.
        """
        symbols = [s.strip() for s in symbols[:50]]
        cache_key = f"prices:{','.join(sorted(s.upper() for s in symbols))}"

        # 1. Check fresh cache
        cached = cache.get(cache_key)
        if cached is not None:
            return cached

        errors: list[Exception] = []

        # 2. Try CoinGecko
        try:
            raw = await coingecko.fetch_prices(symbols)
            items = [PriceData(**r).model_dump() for r in raw]
            result = json.dumps(items, ensure_ascii=False)
            cache.set(cache_key, result, settings.cache_ttl_prices)
            return result
        except Exception as exc:
            log.warning("CoinGecko prices failed: %s", exc)
            errors.append(exc)

        # 3. Stale cache fallback
        stale = cache.get_stale(cache_key, settings.cache_stale_max_age)
        if stale is not None:
            log.info("Returning stale cache for prices")
            return stale

        # 4. CoinCap fallback
        try:
            coincap = _get_coincap()
            raw = await coincap.fetch_prices(symbols)
            items = [PriceData(**r).model_dump() for r in raw]
            result = json.dumps(items, ensure_ascii=False)
            cache.set(cache_key, result, settings.cache_ttl_prices)
            return result
        except Exception as exc:
            log.warning("CoinCap prices failed: %s", exc)
            errors.append(exc)

        raise AllProvidersFailedError(errors)

    @mcp.tool()
    async def get_market_overview() -> str:
        """Get global crypto market overview: total market cap, 24h volume, BTC/ETH dominance.

        Returns:
            JSON object with total_market_cap_usd, total_volume_24h_usd,
            btc_dominance, eth_dominance, active_cryptocurrencies.
        """
        cache_key = "market_overview"
        cached = cache.get(cache_key)
        if cached is not None:
            return cached

        try:
            raw = await coingecko.fetch_market_overview()
            data = MarketOverview(**raw).model_dump()
            result = json.dumps(data, ensure_ascii=False)
            cache.set(cache_key, result, settings.cache_ttl_market_overview)
            return result
        except Exception:
            stale = cache.get_stale(cache_key, settings.cache_stale_max_age)
            if stale is not None:
                return stale
            raise

    @mcp.tool()
    async def get_trending_coins() -> str:
        """Get trending cryptocurrencies in the last 24 hours.

        Returns:
            JSON array with symbol, name, market_cap_rank, price_usd, change_24h.
        """
        cache_key = "trending"
        cached = cache.get(cache_key)
        if cached is not None:
            return cached

        try:
            raw = await coingecko.fetch_trending()
            items = [TrendingCoin(**r).model_dump() for r in raw]
            result = json.dumps(items, ensure_ascii=False)
            cache.set(cache_key, result, settings.cache_ttl_trending)
            return result
        except Exception:
            stale = cache.get_stale(cache_key, settings.cache_stale_max_age)
            if stale is not None:
                return stale
            raise
