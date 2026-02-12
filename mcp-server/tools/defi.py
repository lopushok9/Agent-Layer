"""DeFi-related MCP tools — yields, TVL, fees, stablecoins."""

import json
import logging

from cache import Cache
from config import settings
from models import DefiYield, ProtocolFees, ProtocolTvl, StablecoinData
from providers import defillama
from validation import SUPPORTED_CHAINS_DEFI

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

        Examples:
            Top yields across all chains:
                Input: {"limit": 5}
                Output: [{"pool": "USDC-USDT", "project": "Aave V3", "chain": "Ethereum", "tvl_usd": 450000000, "apy": 5.2, "apy_base": 3.1, "apy_reward": 2.1, "stablecoin": true}]

            Stablecoin yields on Arbitrum with min TVL:
                Input: {"chain": "Arbitrum", "min_tvl": 1000000, "stablecoin_only": true, "limit": 10}
                Output: [{"pool": "USDC-USDT", "project": "GMX", "chain": "Arbitrum", "tvl_usd": 12000000, "apy": 8.5, "apy_base": 8.5, "apy_reward": 0, "stablecoin": true}]
        """
        if chain is not None:
            # DeFiLlama uses capitalized chain names
            chain_cap = chain.strip().capitalize()
            if chain_cap not in SUPPORTED_CHAINS_DEFI:
                raise ValueError(
                    f"Unknown DeFi chain: '{chain}'. "
                    f"Common chains: {', '.join(sorted(SUPPORTED_CHAINS_DEFI))}. "
                    "Note: DeFiLlama uses capitalized names (e.g. 'Ethereum', not 'ethereum')."
                )
            chain = chain_cap
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

        Examples:
            Single protocol:
                Input: {"protocol": "aave"}
                Output: {"name": "Aave", "tvl_usd": 18500000000, "change_1d": 1.2, "change_7d": -0.5, "chains": ["Ethereum", "Arbitrum", "Polygon"], "category": "Lending"}

            Top protocols by TVL:
                Input: {"limit": 3}
                Output: [{"name": "Lido", "tvl_usd": 35000000000, "change_1d": 0.8, "change_7d": 2.1, ...}, {"name": "Aave", "tvl_usd": 18500000000, ...}, {"name": "EigenLayer", "tvl_usd": 15000000000, ...}]
        """
        limit = min(limit, 100)

        if protocol:
            protocol = protocol.strip().lower()
            if not protocol:
                raise ValueError(
                    "Protocol name is required. "
                    'Use slug format: "aave", "uniswap", "lido", "eigenlayer".'
                )
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

        Examples:
            Top 5 protocols by fees:
                Input: {"limit": 5}
                Output: [{"name": "Uniswap", "fees_24h": 3200000, "revenue_24h": 850000, "category": "DEX"}, {"name": "Aave", "fees_24h": 1800000, "revenue_24h": 1200000, "category": "Lending"}]
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

        Examples:
            Top 3 stablecoins:
                Input: {"limit": 3}
                Output: [{"name": "Tether", "symbol": "USDT", "peg_type": "peggedUSD", "circulating_usd": 95000000000, "chains": ["Ethereum", "Tron", "BSC"]}, {"name": "USD Coin", "symbol": "USDC", "peg_type": "peggedUSD", "circulating_usd": 42000000000, "chains": ["Ethereum", "Base", "Arbitrum"]}]
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
