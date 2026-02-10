"""Sentiment MCP tools — Fear & Greed Index."""

import json
import logging

from cache import Cache
from config import settings
from models import FearGreedData
from providers import fear_greed

log = logging.getLogger(__name__)


def register(mcp, cache: Cache):
    """Register sentiment tools on the FastMCP server."""

    @mcp.tool()
    async def get_fear_greed_index() -> str:
        """Get the current Crypto Fear & Greed Index (0-100).

        0-24 = Extreme Fear, 25-49 = Fear, 50 = Neutral, 51-74 = Greed, 75-100 = Extreme Greed.

        Returns:
            JSON object with value (0-100), classification, timestamp.
        """
        cache_key = "fear_greed"
        cached = cache.get(cache_key)
        if cached is not None:
            return cached

        try:
            raw = await fear_greed.fetch_fear_greed()
            data = FearGreedData(**raw).model_dump()
            result = json.dumps(data, ensure_ascii=False)
            cache.set(cache_key, result, settings.cache_ttl_fear_greed)
            return result
        except Exception:
            stale = cache.get_stale(cache_key, settings.cache_stale_max_age)
            if stale is not None:
                return stale
            raise
