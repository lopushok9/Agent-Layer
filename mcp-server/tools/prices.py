"""Price-related MCP tools."""

import json
import logging

from cache import Cache
from config import settings
from exceptions import AllProvidersFailedError
from models import MarketOverview, PriceData, TrendingCoin
from providers import coingecko
from validation import validate_symbols

log = logging.getLogger(__name__)

# Lazy imports to avoid circular deps
_coincap = None
_dexscreener = None


def _get_coincap():
    global _coincap
    if _coincap is None:
        from providers import coincap

        _coincap = coincap
    return _coincap


def _get_dexscreener():
    global _dexscreener
    if _dexscreener is None:
        from providers import dexscreener

        _dexscreener = dexscreener
    return _dexscreener


def register(mcp, cache: Cache):
    """Register price tools on the FastMCP server."""

    @mcp.tool()
    async def get_crypto_prices(symbols: list[str]) -> str:
        """Get current prices for cryptocurrencies.

        Supports major coins (BTC, ETH, SOL) and low-cap/DEX-only tokens via DexScreener.
        Fallback chain: CoinGecko → CoinCap → DexScreener (for tokens not on CEX).

        Args:
            symbols: List of ticker symbols or CoinGecko IDs, e.g. ["BTC", "ETH", "SOL"].
                     Supports up to 50 symbols per request.
                     For low-cap tokens use the exact ticker as shown on DEX (e.g. "BRETT", "TOSHI").

        Returns:
            JSON array with price_usd, change_24h (%), volume_24h, market_cap for each symbol.
            For DEX-sourced tokens, also includes chain, dex, liquidity_usd, pair_url.

        Examples:
            Major coins:
                Input: {"symbols": ["BTC", "ETH", "SOL"]}

            Low-cap DEX token:
                Input: {"symbols": ["BRETT"]}
                Output: [{"symbol": "BRETT", "price_usd": 0.12, "source": "dexscreener", "chain": "base", "dex": "uniswap", "liquidity_usd": 5200000, ...}]

            Mixed (major + low-cap):
                Input: {"symbols": ["ETH", "BRETT", "TOSHI"]}
        """
        symbols = validate_symbols(symbols)
        cache_key = f"prices:{','.join(sorted(s.upper() for s in symbols))}"

        # 1. Check fresh cache
        cached = cache.get(cache_key)
        if cached is not None:
            return cached

        errors: list[Exception] = []
        all_items: list[dict] = []
        remaining_symbols: list[str] = list(symbols)

        # 2. Try CoinGecko
        try:
            raw = await coingecko.fetch_prices(remaining_symbols)
            items = [PriceData(**r).model_dump() for r in raw]
            if items:
                all_items.extend(items)
                found = {item["symbol"].upper() for item in items}
                remaining_symbols = [s for s in remaining_symbols if s.upper() not in found]
                if remaining_symbols:
                    log.info("Symbols not found on CoinGecko: %s", remaining_symbols)
        except Exception as exc:
            log.warning("CoinGecko prices failed: %s", exc)
            errors.append(exc)

        # 3. CoinCap fallback for remaining
        if remaining_symbols:
            try:
                coincap = _get_coincap()
                raw = await coincap.fetch_prices(remaining_symbols)
                items = [PriceData(**r).model_dump() for r in raw]
                if items:
                    all_items.extend(items)
                    found = {item["symbol"].upper() for item in items}
                    remaining_symbols = [s for s in remaining_symbols if s.upper() not in found]
                    if remaining_symbols:
                        log.info("Symbols not found on CoinCap: %s", remaining_symbols)
            except Exception as exc:
                log.warning("CoinCap prices failed: %s", exc)
                errors.append(exc)

        # 4. DexScreener fallback for low-cap / DEX-only tokens
        if remaining_symbols:
            try:
                dexscreener = _get_dexscreener()
                raw = await dexscreener.fetch_prices(remaining_symbols)
                # DexScreener returns extra fields (chain, dex, etc.) — keep them all
                all_items.extend(raw)
                found = {item["symbol"].upper() for item in raw}
                remaining_symbols = [s for s in remaining_symbols if s.upper() not in found]
                if remaining_symbols:
                    log.info("Symbols not found on DexScreener: %s", remaining_symbols)
            except Exception as exc:
                log.warning("DexScreener prices failed: %s", exc)
                errors.append(exc)

        # 5. Return results if we have any
        if all_items:
            result = json.dumps(all_items, ensure_ascii=False)
            cache.set(cache_key, result, settings.cache_ttl_prices)
            return result

        # 6. Stale cache fallback
        stale = cache.get_stale(cache_key, settings.cache_stale_max_age)
        if stale is not None:
            log.info("Returning stale cache for prices")
            return stale

        # 7. All failed — give actionable error
        known = sorted(coingecko.TICKER_MAP.keys())
        raise ValueError(
            f"No price data found for: {', '.join(symbols)}. "
            f"Check spelling or use known tickers: {', '.join(known[:25])}... "
            "You can also use CoinGecko IDs like 'bitcoin', 'ethereum', 'solana'. "
            "For low-cap tokens, use the exact ticker symbol as shown on DexScreener."
        )

    @mcp.tool()
    async def get_market_overview() -> str:
        """Get global crypto market overview: total market cap, 24h volume, BTC/ETH dominance.

        Returns:
            JSON object with total_market_cap_usd, total_volume_24h_usd,
            btc_dominance, eth_dominance, active_cryptocurrencies.

        Examples:
            Input: {}
            Output: {"total_market_cap_usd": 3450000000000, "total_volume_24h_usd": 125000000000, "btc_dominance": 57.2, "eth_dominance": 12.8, "active_cryptocurrencies": 15234}
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

        Examples:
            Input: {}
            Output: [{"symbol": "PEPE", "name": "Pepe", "market_cap_rank": 25, "price_usd": 0.0000123, "change_24h": 15.7}, {"symbol": "WIF", "name": "dogwifhat", "market_cap_rank": 42, "price_usd": 2.85, "change_24h": 8.3}]
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
