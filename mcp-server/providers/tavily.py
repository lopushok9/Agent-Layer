"""Tavily provider — AI-optimized search API for crypto news and analysis.

Requires TAVILY_API_KEY. Returns structured search results with content extraction.
"""

import logging

from config import settings
from exceptions import ProviderError
from http_client import get_client
from rate_limiter import RateLimiter

log = logging.getLogger(__name__)

_limiter = RateLimiter(max_calls=settings.rate_limit_tavily, window_seconds=60)


async def search(
    query: str,
    max_results: int = 5,
    search_depth: str = "basic",
    include_domains: list[str] | None = None,
) -> list[dict]:
    """Search the web for crypto-related information.

    Args:
        query: Search query.
        max_results: Max results (1-10).
        search_depth: "basic" (fast) or "advanced" (deeper, costs more).
        include_domains: Limit to specific domains (e.g. ["coindesk.com"]).
    """
    if not settings.tavily_api_key:
        raise ProviderError("tavily", "TAVILY_API_KEY not configured")

    await _limiter.acquire()

    url = f"{settings.tavily_api_url}/search"
    client = get_client()

    payload: dict = {
        "api_key": settings.tavily_api_key,
        "query": query,
        "max_results": min(max_results, 10),
        "search_depth": search_depth,
    }
    if include_domains:
        payload["include_domains"] = include_domains

    try:
        resp = await client.post(url, json=payload)
    except Exception as exc:
        raise ProviderError("tavily", f"HTTP error: {exc}") from exc

    if resp.status_code == 401:
        raise ProviderError("tavily", "Invalid API key")
    if resp.status_code == 429:
        raise ProviderError("tavily", "Rate limit exceeded")
    if resp.status_code != 200:
        raise ProviderError("tavily", f"HTTP {resp.status_code}: {resp.text[:200]}")

    data = resp.json()
    results = data.get("results", [])

    return [
        {
            "title": r.get("title", ""),
            "url": r.get("url", ""),
            "content": r.get("content", ""),
            "score": r.get("score"),
            "source": "tavily",
        }
        for r in results
    ]
