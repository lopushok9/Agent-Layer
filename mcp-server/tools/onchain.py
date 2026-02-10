"""On-chain MCP tools — wallet balances, token balances, transfers, transaction history."""

import json
import logging

from cache import Cache
from config import settings
from models import TokenBalance, TokenTransfer, Transaction, WalletBalance
from providers import alchemy, explorer, rpc

log = logging.getLogger(__name__)


def register(mcp, cache: Cache):
    """Register on-chain tools on the FastMCP server."""

    @mcp.tool()
    async def get_wallet_balance(address: str, chain: str = "ethereum") -> str:
        """Get native token balance for a wallet address.

        Args:
            address: Wallet address (0x...).
            chain: Blockchain — "ethereum", "base", "arbitrum", "polygon", "optimism", "bsc".

        Returns:
            JSON object with address, chain, balance_native.
        """
        cache_key = f"balance:{chain}:{address}"
        cached = cache.get(cache_key)
        if cached is not None:
            return cached

        try:
            raw = await rpc.fetch_balance(address, chain)
            data = WalletBalance(**raw).model_dump()
            result = json.dumps(data, ensure_ascii=False)
            cache.set(cache_key, result, settings.cache_ttl_wallet_balance)
            return result
        except Exception:
            stale = cache.get_stale(cache_key, settings.cache_stale_max_age)
            if stale is not None:
                return stale
            raise

    @mcp.tool()
    async def get_token_transfers(
        address: str, chain: str = "ethereum", limit: int = 20
    ) -> str:
        """Get recent ERC-20 token transfers for a wallet.

        Args:
            address: Wallet address (0x...).
            chain: "ethereum", "arbitrum", or "base" (requires explorer API key).
            limit: Max transfers to return (default 20, max 100).

        Returns:
            JSON array with tx_hash, token_symbol, value, from/to addresses, timestamp.
        """
        limit = min(limit, 100)
        cache_key = f"transfers:{chain}:{address}:{limit}"

        cached = cache.get(cache_key)
        if cached is not None:
            return cached

        try:
            raw = await explorer.fetch_token_transfers(address, chain, limit)
            items = [TokenTransfer(**r).model_dump() for r in raw]
            result = json.dumps(items, ensure_ascii=False)
            cache.set(cache_key, result, settings.cache_ttl_token_transfers)
            return result
        except Exception:
            stale = cache.get_stale(cache_key, settings.cache_stale_max_age)
            if stale is not None:
                return stale
            raise

    @mcp.tool()
    async def get_transaction_history(
        address: str, chain: str = "ethereum", limit: int = 20
    ) -> str:
        """Get recent transactions for a wallet.

        Args:
            address: Wallet address (0x...).
            chain: "ethereum", "arbitrum", or "base" (requires explorer API key).
            limit: Max transactions to return (default 20, max 100).

        Returns:
            JSON array with tx_hash, value_eth, gas_used, status, from/to, timestamp.
        """
        limit = min(limit, 100)
        cache_key = f"txhistory:{chain}:{address}:{limit}"

        cached = cache.get(cache_key)
        if cached is not None:
            return cached

        try:
            raw = await explorer.fetch_transactions(address, chain, limit)
            items = [Transaction(**r).model_dump() for r in raw]
            result = json.dumps(items, ensure_ascii=False)
            cache.set(cache_key, result, settings.cache_ttl_tx_history)
            return result
        except Exception:
            stale = cache.get_stale(cache_key, settings.cache_stale_max_age)
            if stale is not None:
                return stale
            raise

    @mcp.tool()
    async def get_token_balances(address: str, chain: str = "ethereum") -> str:
        """Get all ERC-20 token balances for a wallet address in one call.

        Requires ALCHEMY_API_KEY. Returns non-zero token balances with symbol and amount.

        Args:
            address: Wallet address (0x...).
            chain: "ethereum", "base", "arbitrum", "polygon", or "optimism".

        Returns:
            JSON array with contract_address, symbol, name, balance, decimals.
        """
        cache_key = f"token_balances:{chain}:{address}"
        cached = cache.get(cache_key)
        if cached is not None:
            return cached

        try:
            raw = await alchemy.fetch_token_balances(address, chain)
            items = [TokenBalance(**r).model_dump() for r in raw]
            result = json.dumps(items, ensure_ascii=False)
            cache.set(cache_key, result, settings.cache_ttl_token_balances)
            return result
        except Exception:
            stale = cache.get_stale(cache_key, settings.cache_stale_max_age)
            if stale is not None:
                return stale
            raise
