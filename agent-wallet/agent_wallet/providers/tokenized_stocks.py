"""Canonical tokenized-stock registry for EVM chains.

Base: Coinbase Tokenized Stocks (B20 tokens issued by Coinbase Onchain SPV Ltd),
listed by the official, keyless, paginated API at
https://api.coinbase.com/v1/tokenized-stocks (see
https://docs.base.org/base-chain/asset-issuance/tokenized-stocks-on-base).

Free-text DEX search is unreliable for stocks: the on-chain symbol carries an
issuer suffix ("TSLAc", not "TSLA"), DexScreener's search returns at most 30
pairs across *all* chains (so Base results are often cut before the chain
filter runs), and impersonators reuse tickers. Resolving through the issuer's
own registry by address avoids all three.
"""

from __future__ import annotations

import re
import time
from typing import Any

from agent_wallet.exceptions import ProviderError
from agent_wallet.http_client import get_client

COINBASE_TOKENIZED_STOCKS_URL = "https://api.coinbase.com/v1/tokenized-stocks"
COINBASE_ISSUER = "Coinbase Onchain SPV Ltd (Coinbase Tokenized Stocks)"
COINBASE_REGISTRY_SOURCE = "https://base.org/stocks"
COINBASE_SYMBOL_SUFFIX = "c"

SUPPORTED_NETWORKS = frozenset({"base"})

_CACHE_TTL_SECONDS = 3600
_MAX_PAGES = 20
_cache: dict[str, tuple[float, list[dict[str, Any]]]] = {}

_BASE_NOTICES = [
    "Issued by Coinbase Onchain SPV Ltd under Regulation S: not available to U.S. persons; "
    "the user is responsible for their own eligibility.",
    "A token is an onchain certificate giving economic exposure to the share, not a direct "
    "shareholding. One token does not permanently equal one share: the share-to-token "
    "multiplier changes with reinvested dividends and corporate actions.",
    "Secondary-market trading is permissionless, but issuer policies can block addresses "
    "(e.g. sanctioned ones); a blocked transfer reverts, so rely on the swap simulation.",
    "DEX prices can drift from the underlying stock outside U.S. market hours.",
]


def _normalize_ticker(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", value.strip().lower())


def _clean_token(raw: dict[str, Any]) -> dict[str, Any] | None:
    address = str(raw.get("contract_address") or "").strip()
    symbol = str(raw.get("symbol") or "").strip()
    if not re.fullmatch(r"0x[0-9a-fA-F]{40}", address) or not symbol:
        return None
    try:
        decimals = int(raw.get("decimals"))
    except (TypeError, ValueError):
        decimals = None
    multiplier = raw.get("multiplier")
    underlying = symbol[: -len(COINBASE_SYMBOL_SUFFIX)] if symbol.endswith(COINBASE_SYMBOL_SUFFIX) else symbol
    return {
        "address": address,
        "symbol": symbol,
        "underlying_ticker": underlying,
        "name": str(raw.get("name") or "").strip() or None,
        "decimals": decimals,
        "isin": str(raw.get("isin") or "").strip() or None,
        "multiplier": multiplier if isinstance(multiplier, (int, float)) else None,
    }


async def _fetch_coinbase_registry() -> list[dict[str, Any]]:
    cached = _cache.get("base")
    if cached is not None and time.monotonic() - cached[0] <= _CACHE_TTL_SECONDS:
        return cached[1]
    client = get_client()
    tokens: list[dict[str, Any]] = []
    page_token: str | None = None
    for _ in range(_MAX_PAGES):
        params = {"page_token": page_token} if page_token else None
        try:
            response = await client.get(COINBASE_TOKENIZED_STOCKS_URL, params=params)
        except Exception as exc:  # network errors
            if cached is not None:
                return cached[1]
            raise ProviderError("coinbase-tokenized-stocks", f"Request failed: {exc}") from exc
        if response.status_code != 200:
            if cached is not None:
                return cached[1]
            raise ProviderError(
                "coinbase-tokenized-stocks", f"HTTP {response.status_code}: {response.text[:300]}"
            )
        try:
            data = response.json()
        except ValueError as exc:
            raise ProviderError("coinbase-tokenized-stocks", "Unexpected non-JSON response.") from exc
        for raw in data.get("tokens") or []:
            if isinstance(raw, dict):
                token = _clean_token(raw)
                if token is not None:
                    tokens.append(token)
        page_token = str(data.get("next_page_token") or "").strip() or None
        if not page_token:
            break
    if not tokens:
        if cached is not None:
            return cached[1]
        raise ProviderError("coinbase-tokenized-stocks", "Registry returned no tokens.")
    _cache["base"] = (time.monotonic(), tokens)
    return tokens


def _score(token: dict[str, Any], query: str) -> int:
    """Higher is better; 0 means no match."""
    q = _normalize_ticker(query)
    if not q:
        return 0
    if token["address"].lower() == query.strip().lower():
        return 100
    symbol = _normalize_ticker(token["symbol"])
    underlying = _normalize_ticker(token["underlying_ticker"])
    if q in {symbol, underlying} or (token.get("isin") and q == _normalize_ticker(token["isin"])):
        return 90
    name = (token.get("name") or "").lower()
    name_key = _normalize_ticker(name)
    words = [_normalize_ticker(word) for word in re.split(r"[\s,.]+", name) if word]
    if q == name_key or (words and q == words[0]):
        return 70
    if len(q) >= 3 and (name_key.startswith(q) or q in words):
        return 50
    if len(q) >= 4 and q in name_key:
        return 30
    return 0


def is_supported_network(network: str | None) -> bool:
    return str(network or "").strip().lower() in SUPPORTED_NETWORKS


async def find_tokenized_stocks(
    query: str,
    *,
    network: str = "base",
    limit: int = 5,
) -> dict[str, Any]:
    """Resolve a ticker, company name, ISIN or address to canonical tokenized stocks."""
    network = str(network or "").strip().lower()
    query = str(query or "").strip()
    if not query:
        raise ProviderError("tokenized-stocks", "query must not be empty.")
    if network not in SUPPORTED_NETWORKS:
        raise ProviderError(
            "tokenized-stocks",
            f"No canonical tokenized-stock registry is wired for network '{network}'. "
            "Supported: base (Coinbase Tokenized Stocks). For robinhood, verify the address "
            "against docs.robinhood.com/chain/contracts.",
        )
    registry = await _fetch_coinbase_registry()
    scored = [(score, token) for token in registry if (score := _score(token, query)) > 0]
    scored.sort(key=lambda item: (-item[0], item[1]["symbol"]))
    bounded = max(1, min(int(limit or 5), 20))
    # A unique company-name match ("Tesla") is as unambiguous as a ticker match.
    unique_name_match = sum(1 for score, _ in scored if score >= 70) == 1
    matches = [
        {
            **token,
            "match_score": score,
            "exact_match": score >= 90 or (score >= 70 and unique_name_match),
        }
        for score, token in scored[:bounded]
    ]
    return {
        "network": network,
        "query": query,
        "issuer": COINBASE_ISSUER,
        "registry_source": COINBASE_REGISTRY_SOURCE,
        "registry_size": len(registry),
        "count": len(matches),
        "matches": matches,
        "notices": list(_BASE_NOTICES),
    }


async def canonical_address_set(network: str) -> set[str]:
    if not is_supported_network(network):
        return set()
    registry = await _fetch_coinbase_registry()
    return {token["address"].lower() for token in registry}
