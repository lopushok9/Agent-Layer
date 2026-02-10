"""Alternative.me Fear & Greed Index — free, no key required."""

import logging

from config import settings
from exceptions import ProviderError
from http_client import get_client

log = logging.getLogger(__name__)


async def fetch_fear_greed() -> dict:
    """Fetch current Fear & Greed Index."""
    url = f"{settings.fear_greed_url}/"
    client = get_client()
    try:
        resp = await client.get(url, params={"limit": "1", "format": "json"})
    except Exception as exc:
        raise ProviderError("fear_greed", f"HTTP error: {exc}") from exc

    if resp.status_code != 200:
        raise ProviderError("fear_greed", f"HTTP {resp.status_code}: {resp.text[:200]}")

    data = resp.json()
    items = data.get("data", [])
    if not items:
        raise ProviderError("fear_greed", "No data in response")

    entry = items[0]
    return {
        "value": int(entry.get("value", 0)),
        "classification": entry.get("value_classification", ""),
        "timestamp": entry.get("timestamp", ""),
        "source": "alternative.me",
    }
