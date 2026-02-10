"""Etherscan-family explorer provider — free API keys, 100k calls/day.

Supports Etherscan, Arbiscan, Basescan with identical API interface.
"""

import logging

from config import settings
from exceptions import ProviderError
from http_client import get_client
from rate_limiter import RateLimiter

log = logging.getLogger(__name__)

_limiter = RateLimiter(max_calls=settings.rate_limit_explorer, window_seconds=60)

# Chain → (base_url, api_key)
EXPLORERS: dict[str, tuple[str, str]] = {
    "ethereum": (settings.etherscan_api_url, settings.etherscan_api_key),
    "arbitrum": (settings.arbiscan_api_url, settings.arbiscan_api_key),
    "base": (settings.basescan_api_url, settings.basescan_api_key),
}


def _get_explorer(chain: str) -> tuple[str, str]:
    chain_lower = chain.lower()
    if chain_lower not in EXPLORERS:
        raise ProviderError(
            "explorer",
            f"Unsupported chain: {chain}. Supported: {', '.join(EXPLORERS)}",
        )
    base_url, api_key = EXPLORERS[chain_lower]
    if not api_key:
        raise ProviderError(
            "explorer",
            f"No API key configured for {chain}. Set the corresponding env var "
            f"(e.g. ETHERSCAN_API_KEY). Free keys at etherscan.io/myapikey",
        )
    return base_url, api_key


async def _get(chain: str, params: dict) -> dict:
    await _limiter.acquire()
    base_url, api_key = _get_explorer(chain)
    params["apikey"] = api_key
    client = get_client()
    try:
        resp = await client.get(base_url, params=params)
    except Exception as exc:
        raise ProviderError("explorer", f"HTTP error: {exc}") from exc

    if resp.status_code != 200:
        raise ProviderError("explorer", f"HTTP {resp.status_code}: {resp.text[:200]}")

    data = resp.json()
    if data.get("status") == "0" and data.get("message") != "No transactions found":
        raise ProviderError("explorer", f"API error: {data.get('result', data.get('message', '?'))}")
    return data


async def fetch_token_transfers(address: str, chain: str, limit: int = 20) -> list[dict]:
    """ERC-20 token transfers for an address."""
    data = await _get(
        chain,
        {
            "module": "account",
            "action": "tokentx",
            "address": address,
            "page": "1",
            "offset": str(min(limit, 100)),
            "sort": "desc",
        },
    )
    txs = data.get("result", [])
    if not isinstance(txs, list):
        return []

    results = []
    for tx in txs[:limit]:
        decimals = int(tx.get("tokenDecimal", 18) or 18)
        raw_value = int(tx.get("value", 0) or 0)
        value = raw_value / (10**decimals) if decimals else raw_value
        results.append(
            {
                "tx_hash": tx.get("hash", ""),
                "block_number": int(tx.get("blockNumber", 0) or 0),
                "timestamp": tx.get("timeStamp", ""),
                "from_address": tx.get("from", ""),
                "to_address": tx.get("to", ""),
                "token_symbol": tx.get("tokenSymbol", "?"),
                "value": value,
                "source": "etherscan",
            }
        )
    return results


async def fetch_transactions(address: str, chain: str, limit: int = 20) -> list[dict]:
    """Normal transactions for an address."""
    data = await _get(
        chain,
        {
            "module": "account",
            "action": "txlist",
            "address": address,
            "page": "1",
            "offset": str(min(limit, 100)),
            "sort": "desc",
        },
    )
    txs = data.get("result", [])
    if not isinstance(txs, list):
        return []

    results = []
    for tx in txs[:limit]:
        value_wei = int(tx.get("value", 0) or 0)
        gas_used = int(tx.get("gasUsed", 0) or 0)
        gas_price = int(tx.get("gasPrice", 0) or 0)
        results.append(
            {
                "tx_hash": tx.get("hash", ""),
                "block_number": int(tx.get("blockNumber", 0) or 0),
                "timestamp": tx.get("timeStamp", ""),
                "from_address": tx.get("from", ""),
                "to_address": tx.get("to", ""),
                "value_eth": value_wei / 1e18,
                "gas_used": gas_used,
                "gas_price_gwei": gas_price / 1e9,
                "status": "success" if tx.get("txreceipt_status") == "1" else "failed",
                "source": "etherscan",
            }
        )
    return results


async def fetch_gas_oracle(chain: str) -> dict | None:
    """Gas prices from explorer's gas oracle (Ethereum only typically)."""
    try:
        data = await _get(
            chain,
            {"module": "gastracker", "action": "gasoracle"},
        )
        result = data.get("result", {})
        if not isinstance(result, dict):
            return None
        return {
            "chain": chain.lower(),
            "slow_gwei": float(result.get("SafeGasPrice", 0)),
            "standard_gwei": float(result.get("ProposeGasPrice", 0)),
            "fast_gwei": float(result.get("FastGasPrice", 0)),
            "source": "explorer",
        }
    except Exception:
        return None
