"""Gas price MCP tools."""

import json
import logging

from cache import Cache
from config import settings
from models import GasPrice
from providers import explorer, rpc

log = logging.getLogger(__name__)


def register(mcp, cache: Cache):
    """Register gas tools on the FastMCP server."""

    @mcp.tool()
    async def get_gas_prices(chain: str = "ethereum") -> str:
        """Get current gas prices (slow/standard/fast) for a chain.

        Args:
            chain: Blockchain — "ethereum", "base", "arbitrum", "polygon", "optimism", "bsc".

        Returns:
            JSON object with slow_gwei, standard_gwei, fast_gwei.
        """
        cache_key = f"gas:{chain}"
        cached = cache.get(cache_key)
        if cached is not None:
            return cached

        raw = None

        # Try explorer gas oracle first (more accurate slow/standard/fast split)
        try:
            raw = await explorer.fetch_gas_oracle(chain)
        except Exception:
            pass

        # Fallback to RPC eth_gasPrice
        if raw is None:
            try:
                raw = await rpc.fetch_gas_price(chain)
            except Exception:
                stale = cache.get_stale(cache_key, settings.cache_stale_max_age)
                if stale is not None:
                    return stale
                raise

        data = GasPrice(**raw).model_dump()
        result = json.dumps(data, ensure_ascii=False)
        cache.set(cache_key, result, settings.cache_ttl_gas)
        return result
