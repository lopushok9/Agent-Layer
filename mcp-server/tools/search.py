"""Search MCP tools — crypto news and analysis via Tavily."""

import json
import logging

from cache import Cache
from config import settings
from models import SearchResult
from providers import tavily

log = logging.getLogger(__name__)


def register(mcp, cache: Cache):
    """Register search tools on the FastMCP server."""

    @mcp.tool()
    async def search_crypto(
        query: str,
        max_results: int = 5,
    ) -> str:
        """Search for crypto news, analysis, and information.

        Uses Tavily AI search. Requires TAVILY_API_KEY.

        Args:
            query: Search query, e.g. "Bitcoin ETF latest news" or "Ethereum Dencun upgrade".
            max_results: Number of results (default 5, max 10).

        Returns:
            JSON array with title, url, content snippet, relevance score.

        Examples:
            Search for Bitcoin news:
                Input: {"query": "Bitcoin ETF inflows 2026", "max_results": 3}
                Output: [{"title": "Bitcoin ETF Sees Record $1.2B Daily Inflow", "url": "https://...", "content": "Spot Bitcoin ETFs recorded...", "score": 0.95}]

            Search for protocol analysis:
                Input: {"query": "Aave v4 launch date features"}
                Output: [{"title": "Aave V4: Everything You Need to Know", "url": "https://...", "content": "Aave's upcoming V4 introduces...", "score": 0.88}]
        """
        max_results = min(max_results, 10)
        cache_key = f"search:{query}:{max_results}"

        cached = cache.get(cache_key)
        if cached is not None:
            return cached

        try:
            raw = await tavily.search(query, max_results=max_results)
            items = [SearchResult(**r).model_dump() for r in raw]
            result = json.dumps(items, ensure_ascii=False)
            cache.set(cache_key, result, settings.cache_ttl_search)
            return result
        except Exception:
            stale = cache.get_stale(cache_key, settings.cache_stale_max_age)
            if stale is not None:
                return stale
            raise
