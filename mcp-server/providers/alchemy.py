"""Alchemy provider — enhanced RPC with token balance support.

Uses alchemy_getTokenBalances to fetch ALL ERC-20 tokens for a wallet
in a single call (vs. Etherscan which requires one call per token).

Requires ALCHEMY_API_KEY. Falls back gracefully if not configured.
"""

import logging

from config import settings
from exceptions import ProviderError
from http_client import get_client
from rate_limiter import RateLimiter

log = logging.getLogger(__name__)

_limiter = RateLimiter(max_calls=settings.rate_limit_alchemy, window_seconds=60)

# Alchemy RPC base URLs per chain (key is appended)
ALCHEMY_CHAINS: dict[str, str] = {
    "ethereum": "https://eth-mainnet.g.alchemy.com/v2",
    "base": "https://base-mainnet.g.alchemy.com/v2",
    "arbitrum": "https://arb-mainnet.g.alchemy.com/v2",
    "polygon": "https://polygon-mainnet.g.alchemy.com/v2",
    "optimism": "https://opt-mainnet.g.alchemy.com/v2",
}

# Well-known token metadata (symbol, name, decimals) for top tokens.
# Alchemy returns contract addresses but NOT symbols/names in getTokenBalances.
# We map the most popular ones; unknown tokens show contract address.
TOKEN_METADATA: dict[str, dict[str, tuple[str, str, int]]] = {
    "ethereum": {
        "0xdac17f958d2ee523a2206206994597c13d831ec7": ("USDT", "Tether USD", 6),
        "0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48": ("USDC", "USD Coin", 6),
        "0x6b175474e89094c44da98b954eedeac495271d0f": ("DAI", "Dai", 18),
        "0x2260fac5e5542a773aa44fbcfedf7c193bc2c599": ("WBTC", "Wrapped BTC", 8),
        "0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2": ("WETH", "Wrapped Ether", 18),
        "0x7f39c581f595b53c5cb19bd0b3f8da6c935e2ca0": ("wstETH", "Wrapped stETH", 18),
        "0xae78736cd615f374d3085123a210448e74fc6393": ("rETH", "Rocket Pool ETH", 18),
        "0x514910771af9ca656af840dff83e8264ecf986ca": ("LINK", "Chainlink", 18),
        "0x1f9840a85d5af5bf1d1762f925bdaddc4201f984": ("UNI", "Uniswap", 18),
        "0x7fc66500c84a76ad7e9c93437bfc5ac33e2ddae9": ("AAVE", "Aave", 18),
        "0x9f8f72aa9304c8b593d555f12ef6589cc3a579a2": ("MKR", "Maker", 18),
        "0x5a98fcbea516cf06857215779fd812ca3bef1b32": ("LDO", "Lido DAO", 18),
        "0xd533a949740bb3306d119cc777fa900ba034cd52": ("CRV", "Curve DAO", 18),
        "0x95ad61b0a150d79219dcf64e1e6cc01f0b64c4ce": ("SHIB", "Shiba Inu", 18),
        "0x6982508145454ce325ddbe47a25d4ec3d2311933": ("PEPE", "Pepe", 18),
    },
    "arbitrum": {
        "0xfd086bc7cd5c481dcc9c85ebe478a1c0b69fcbb9": ("USDT", "Tether USD", 6),
        "0xaf88d065e77c8cc2239327c5edb3a432268e5831": ("USDC", "USD Coin", 6),
        "0xff970a61a04b1ca14834a43f5de4533ebddb5cc8": ("USDC.e", "Bridged USDC", 6),
        "0xda10009cbd5d07dd0cecc66161fc93d7c9000da1": ("DAI", "Dai", 18),
        "0x2f2a2543b76a4166549f7aab2e75bef0aefc5b0f": ("WBTC", "Wrapped BTC", 8),
        "0x82af49447d8a07e3bd95bd0d56f35241523fbab1": ("WETH", "Wrapped Ether", 18),
        "0x912ce59144191c1204e64559fe8253a0e49e6548": ("ARB", "Arbitrum", 18),
        "0xf97f4df75117a78c1a5a0dbb814af92458539fb4": ("LINK", "Chainlink", 18),
        "0xfa7f8980b0f1e64a2062791cc3b0871572f1f7f0": ("UNI", "Uniswap", 18),
    },
    "base": {
        "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913": ("USDC", "USD Coin", 6),
        "0x50c5725949a6f0c72e6c4a641f24049a917db0cb": ("DAI", "Dai", 18),
        "0x4200000000000000000000000000000000000006": ("WETH", "Wrapped Ether", 18),
        "0x2ae3f1ec7f1f5012cfeab0185bfc7aa3cf0dec22": ("cbETH", "Coinbase ETH", 18),
    },
    "polygon": {
        "0xc2132d05d31c914a87c6611c10748aeb04b58e8f": ("USDT", "Tether USD", 6),
        "0x3c499c542cef5e3811e1192ce70d8cc03d5c3359": ("USDC", "USD Coin", 6),
        "0x2791bca1f2de4661ed88a30c99a7a9449aa84174": ("USDC.e", "Bridged USDC", 6),
        "0x8f3cf7ad23cd3cadbd9735aff958023239c6a063": ("DAI", "Dai", 18),
        "0x1bfd67037b42cf73acf2047067bd4f2c47d9bfd6": ("WBTC", "Wrapped BTC", 8),
        "0x7ceb23fd6bc0add59e62ac25578270cff1b9f619": ("WETH", "Wrapped Ether", 18),
        "0x0d500b1d8e8ef31e21c99d1db9a6444d3adf1270": ("WPOL", "Wrapped POL", 18),
        "0x53e0bca35ec356bd5dddfebbd1fc0fd03fabad39": ("LINK", "Chainlink", 18),
        "0xb33eaad8d922b1083446dc23f610c2567fb5180f": ("UNI", "Uniswap", 18),
        "0xd6df932a45c0f255f85145f286ea0b292b21c90b": ("AAVE", "Aave", 18),
    },
    "optimism": {
        "0x94b008aa00579c1307b0ef2c499ad98a8ce58e58": ("USDT", "Tether USD", 6),
        "0x0b2c639c533813f4aa9d7837caf62653d097ff85": ("USDC", "USD Coin", 6),
        "0x7f5c764cbc14f9669b88837ca1490cca17c31607": ("USDC.e", "Bridged USDC", 6),
        "0xda10009cbd5d07dd0cecc66161fc93d7c9000da1": ("DAI", "Dai", 18),
        "0x68f180fcce6836688e9084f035309e29bf0a2095": ("WBTC", "Wrapped BTC", 8),
        "0x4200000000000000000000000000000000000006": ("WETH", "Wrapped Ether", 18),
        "0x4200000000000000000000000000000000000042": ("OP", "Optimism", 18),
        "0x350a791bfc2c21f9ed5d10980dad2e2638ffa7f6": ("LINK", "Chainlink", 18),
    },
}


def _get_rpc_url(chain: str) -> str:
    """Build Alchemy RPC URL for chain."""
    chain_lower = chain.lower()
    if not settings.alchemy_api_key:
        raise ProviderError("alchemy", "ALCHEMY_API_KEY not configured")
    base = ALCHEMY_CHAINS.get(chain_lower)
    if not base:
        raise ProviderError(
            "alchemy",
            f"Unsupported chain: {chain}. Supported: {', '.join(ALCHEMY_CHAINS)}",
        )
    return f"{base}/{settings.alchemy_api_key}"


def _resolve_token(chain: str, contract: str) -> tuple[str | None, str | None, int]:
    """Resolve contract address to (symbol, name, decimals)."""
    chain_meta = TOKEN_METADATA.get(chain.lower(), {})
    meta = chain_meta.get(contract.lower())
    if meta:
        return meta
    return (None, None, 18)  # default 18 decimals


async def _rpc_call(chain: str, method: str, params: list) -> dict:
    """Execute JSON-RPC call against Alchemy."""
    await _limiter.acquire()
    url = _get_rpc_url(chain)
    client = get_client()
    payload = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}
    try:
        resp = await client.post(url, json=payload)
    except Exception as exc:
        raise ProviderError("alchemy", f"HTTP error on {chain}: {exc}") from exc

    if resp.status_code != 200:
        raise ProviderError("alchemy", f"HTTP {resp.status_code} on {chain}")

    data = resp.json()
    if "error" in data:
        raise ProviderError("alchemy", f"RPC error: {data['error']}")
    return data


async def fetch_token_balances(address: str, chain: str) -> list[dict]:
    """Fetch ERC-20 token balances for an address.

    Queries known tokens (from TOKEN_METADATA) by contract address for
    accurate results without spam.  Falls back to "erc20" scan if no
    metadata is available for the chain.
    """
    chain_lower = chain.lower()
    chain_meta = TOKEN_METADATA.get(chain_lower, {})

    if chain_meta:
        # Query specific known token addresses — 1 call, no spam
        token_addresses = list(chain_meta.keys())
        data = await _rpc_call(
            chain,
            "alchemy_getTokenBalances",
            [address, token_addresses],
        )
    else:
        # No metadata for this chain — scan all ERC-20
        data = await _rpc_call(
            chain,
            "alchemy_getTokenBalances",
            [address, "erc20"],
        )

    result_obj = data.get("result", {})
    token_balances = result_obj.get("tokenBalances", [])

    results = []
    for tb in token_balances:
        contract = tb.get("contractAddress", "")
        hex_balance = tb.get("tokenBalance", "0x0")

        if hex_balance in ("0x0", "0x", None, ""):
            continue

        raw_balance = int(hex_balance, 16)
        if raw_balance == 0:
            continue

        symbol, name, decimals = _resolve_token(chain, contract)
        balance = raw_balance / (10**decimals)

        # Skip dust
        if balance < 0.0001:
            continue

        results.append(
            {
                "contract_address": contract,
                "symbol": symbol,
                "name": name,
                "balance": balance,
                "decimals": decimals,
                "source": "alchemy",
            }
        )

    # Sort by balance descending
    results.sort(key=lambda x: x["balance"], reverse=True)
    return results
