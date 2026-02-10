"""RPC provider — Alchemy (primary) + PublicNode (fallback).

Uses JSON-RPC to query native balances and gas prices.
If the primary RPC (from .env, typically Alchemy) fails,
automatically retries with free PublicNode endpoints.
"""

import logging

from config import settings
from exceptions import ProviderError
from http_client import get_client

log = logging.getLogger(__name__)

# Primary RPC URLs (from .env — Alchemy when configured)
CHAIN_RPC_PRIMARY: dict[str, str] = {
    "ethereum": settings.eth_rpc_url,
    "base": settings.base_rpc_url,
    "arbitrum": settings.arbitrum_rpc_url,
    "polygon": settings.polygon_rpc_url,
    "optimism": settings.optimism_rpc_url,
    "bsc": settings.bsc_rpc_url,
}

# Fallback RPC URLs — PublicNode, free, no key, always available
CHAIN_RPC_FALLBACK: dict[str, str] = {
    "ethereum": "https://ethereum-rpc.publicnode.com",
    "base": "https://base-rpc.publicnode.com",
    "arbitrum": "https://arbitrum-one-rpc.publicnode.com",
    "polygon": "https://polygon-bor-rpc.publicnode.com",
    "optimism": "https://optimism-rpc.publicnode.com",
    "bsc": "https://bsc-rpc.publicnode.com",
}

CHAIN_NATIVE_SYMBOL: dict[str, str] = {
    "ethereum": "ETH",
    "base": "ETH",
    "arbitrum": "ETH",
    "polygon": "POL",
    "optimism": "ETH",
    "bsc": "BNB",
}

CHAIN_DECIMALS: dict[str, int] = {
    "ethereum": 18,
    "base": 18,
    "arbitrum": 18,
    "polygon": 18,
    "optimism": 18,
    "bsc": 18,
}


async def _do_rpc_call(rpc_url: str, chain: str, method: str, params: list) -> dict:
    """Execute a single JSON-RPC call."""
    client = get_client()
    payload = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}
    resp = await client.post(rpc_url, json=payload)
    if resp.status_code == 429:
        raise ProviderError("rpc", f"Rate limited on {chain} ({rpc_url[:40]}...)")
    if resp.status_code != 200:
        raise ProviderError("rpc", f"HTTP {resp.status_code} on {chain}")
    data = resp.json()
    if "error" in data:
        raise ProviderError("rpc", f"RPC error on {chain}: {data['error']}")
    return data


async def _rpc_call(chain: str, method: str, params: list) -> dict:
    """Execute JSON-RPC with fallback: primary (Alchemy) → PublicNode."""
    chain_lower = chain.lower()
    primary_url = CHAIN_RPC_PRIMARY.get(chain_lower)
    fallback_url = CHAIN_RPC_FALLBACK.get(chain_lower)

    if not primary_url and not fallback_url:
        raise ProviderError("rpc", f"Unsupported chain: {chain}. Supported: {', '.join(CHAIN_RPC_PRIMARY)}")

    # Try primary
    if primary_url:
        try:
            return await _do_rpc_call(primary_url, chain_lower, method, params)
        except Exception as exc:
            log.warning("Primary RPC failed for %s: %s — trying PublicNode fallback", chain_lower, exc)

    # Fallback to PublicNode
    if fallback_url and fallback_url != primary_url:
        try:
            return await _do_rpc_call(fallback_url, chain_lower, method, params)
        except Exception as exc:
            raise ProviderError("rpc", f"Both primary and fallback RPC failed on {chain}: {exc}") from exc

    raise ProviderError("rpc", f"RPC failed on {chain}, no fallback available")


async def fetch_balance(address: str, chain: str) -> dict:
    """Get native token balance for an address."""
    chain_lower = chain.lower()
    data = await _rpc_call(chain_lower, "eth_getBalance", [address, "latest"])
    hex_balance = data.get("result", "0x0")
    wei = int(hex_balance, 16)
    decimals = CHAIN_DECIMALS.get(chain_lower, 18)
    balance = wei / (10**decimals)

    return {
        "address": address,
        "chain": chain_lower,
        "balance_native": balance,
        "balance_usd": None,
        "source": "rpc",
    }


async def fetch_gas_price(chain: str) -> dict:
    """Get current gas price from RPC."""
    chain_lower = chain.lower()
    data = await _rpc_call(chain_lower, "eth_gasPrice", [])
    hex_gas = data.get("result", "0x0")
    gas_wei = int(hex_gas, 16)
    gas_gwei = gas_wei / 1e9

    return {
        "chain": chain_lower,
        "slow_gwei": round(gas_gwei * 0.8, 2),
        "standard_gwei": round(gas_gwei, 2),
        "fast_gwei": round(gas_gwei * 1.3, 2),
        "source": "rpc",
    }
