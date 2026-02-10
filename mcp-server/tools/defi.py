"""DeFi-related MCP tools — yields, TVL, fees, stablecoins."""

import json
import logging

from cache import Cache
from config import settings
from models import DefiYield, ProtocolFees, ProtocolTvl, StablecoinData
from providers import defillama

log = logging.getLogger(__name__)


def register(mcp, cache: Cache):
    """Register DeFi tools on the FastMCP server."""

    @mcp.tool()
    async def get_defi_yields(
        chain: str | None = None,
        min_tvl: float = 0,
        stablecoin_only: bool = False,
        limit: int = 20,
    ) -> str:
        """Get top DeFi yield opportunities across protocols.

        Args:
            chain: Filter by chain name (e.g. "Ethereum", "Arbitrum", "Base"). None for all chains.
            min_tvl: Minimum TVL in USD to filter pools (default 0).
            stablecoin_only: If True, only return stablecoin pools.
            limit: Max number of results (default 20, max 100).

        Returns:
            JSON array with pool name, project, chain, tvl_usd, apy, stablecoin flag.
        """
        limit = min(limit, 100)
        cache_key = f"yields:{chain}:{min_tvl}:{stablecoin_only}:{limit}"

        cached = cache.get(cache_key)
        if cached is not None:
            return cached

        try:
            raw = await defillama.fetch_yields(chain, min_tvl, stablecoin_only, limit)
            items = [DefiYield(**r).model_dump() for r in raw]
            result = json.dumps(items, ensure_ascii=False)
            cache.set(cache_key, result, settings.cache_ttl_defi_yields)
            return result
        except Exception:
            stale = cache.get_stale(cache_key, settings.cache_stale_max_age)
            if stale is not None:
                return stale
            raise

    @mcp.tool()
    async def get_protocol_tvl(protocol: str | None = None, limit: int = 20) -> str:
        """Get Total Value Locked (TVL) for a specific protocol or top protocols.

        Args:
            protocol: Protocol slug (e.g. "aave", "uniswap", "lido"). None for top protocols by TVL.
            limit: Number of top protocols to return if protocol is None (default 20, max 100).

        Returns:
            JSON object (single protocol) or JSON array (top protocols) with name, tvl_usd, change_1d, change_7d.
        """
        limit = min(limit, 100)

        if protocol:
            cache_key = f"tvl:{protocol}"
        else:
            cache_key = f"tvl:top:{limit}"

        cached = cache.get(cache_key)
        if cached is not None:
            return cached

        try:
            if protocol:
                raw = await defillama.fetch_protocol_tvl(protocol)
                data = ProtocolTvl(**raw).model_dump()
            else:
                raw_list = await defillama.fetch_protocols(limit)
                data = [ProtocolTvl(**r).model_dump() for r in raw_list]

            result = json.dumps(data, ensure_ascii=False)
            cache.set(cache_key, result, settings.cache_ttl_protocol_tvl)
            return result
        except Exception:
            stale = cache.get_stale(cache_key, settings.cache_stale_max_age)
            if stale is not None:
                return stale
            raise

    @mcp.tool()
    async def get_protocol_fees(limit: int = 20) -> str:
        """Get protocol fees and revenue for the last 24 hours.

        Args:
            limit: Number of top protocols by fees (default 20, max 100).

        Returns:
            JSON array with name, fees_24h, revenue_24h, category.
        """
        limit = min(limit, 100)
        cache_key = f"fees:{limit}"

        cached = cache.get(cache_key)
        if cached is not None:
            return cached

        try:
            raw = await defillama.fetch_fees(limit)
            items = [ProtocolFees(**r).model_dump() for r in raw]
            result = json.dumps(items, ensure_ascii=False)
            cache.set(cache_key, result, settings.cache_ttl_protocol_fees)
            return result
        except Exception:
            stale = cache.get_stale(cache_key, settings.cache_stale_max_age)
            if stale is not None:
                return stale
            raise

    @mcp.tool()
    async def get_stablecoin_stats(limit: int = 20) -> str:
        """Get stablecoin market data: circulating supply, peg type, chains.

        Args:
            limit: Number of top stablecoins (default 20, max 50).

        Returns:
            JSON array with name, symbol, peg_type, circulating_usd, chains.
        """
        limit = min(limit, 50)
        cache_key = f"stablecoins:{limit}"

        cached = cache.get(cache_key)
        if cached is not None:
            return cached

        try:
            raw = await defillama.fetch_stablecoins(limit)
            items = [StablecoinData(**r).model_dump() for r in raw]
            result = json.dumps(items, ensure_ascii=False)
            cache.set(cache_key, result, settings.cache_ttl_stablecoins)
            return result
        except Exception:
            stale = cache.get_stale(cache_key, settings.cache_stale_max_age)
            if stale is not None:
                return stale
            raise
