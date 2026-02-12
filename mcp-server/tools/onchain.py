"""On-chain MCP tools — wallet balances, token balances, transfers, transaction history, portfolio."""

import json
import logging

from cache import Cache
from config import settings
from models import (
    PortfolioToken,
    TokenBalance,
    TokenTransfer,
    Transaction,
    WalletBalance,
    WalletPortfolio,
)
from providers import alchemy, coingecko, explorer, rpc

log = logging.getLogger(__name__)


async def _fetch_native_price(chain: str, cache: Cache) -> float | None:
    """Get native token USD price from cache or CoinGecko."""
    symbol = rpc.CHAIN_NATIVE_SYMBOL.get(chain.lower(), "ETH")
    cache_key = f"native_price:{symbol}"

    cached = cache.get(cache_key)
    if cached is not None:
        return float(cached)

    try:
        prices = await coingecko.fetch_prices([symbol])
        if prices:
            price = prices[0].get("price_usd", 0)
            if price:
                cache.set(cache_key, str(price), settings.cache_ttl_prices)
                return price
    except Exception as exc:
        log.debug("Native price fetch failed for %s: %s", symbol, exc)

    return None


def register(mcp, cache: Cache):
    """Register on-chain tools on the FastMCP server."""

    @mcp.tool()
    async def get_wallet_balance(address: str, chain: str = "ethereum") -> str:
        """Get native token balance for a wallet address with USD value.

        Args:
            address: Wallet address (0x...).
            chain: Blockchain — "ethereum", "base", "arbitrum", "polygon", "optimism", "bsc".

        Returns:
            JSON object with address, chain, balance_native, balance_usd.

        Examples:
            Ethereum balance:
                Input: {"address": "0xd8dA6BF26964aF9D7eEd9e03E53415D37aA96045", "chain": "ethereum"}
                Output: {"address": "0xd8dA6BF26964aF9D7eEd9e03E53415D37aA96045", "chain": "ethereum", "balance_native": 1250.75, "balance_usd": 3940112.5}

            Arbitrum balance:
                Input: {"address": "0xd8dA6BF26964aF9D7eEd9e03E53415D37aA96045", "chain": "arbitrum"}
                Output: {"address": "0xd8dA6BF26964aF9D7eEd9e03E53415D37aA96045", "chain": "arbitrum", "balance_native": 3.42, "balance_usd": 10773.0}
        """
        cache_key = f"balance:{chain}:{address}"
        cached = cache.get(cache_key)
        if cached is not None:
            return cached

        try:
            raw = await rpc.fetch_balance(address, chain)

            # Enrich with USD price
            native_price = await _fetch_native_price(chain, cache)
            if native_price and raw["balance_native"] > 0:
                raw["balance_usd"] = round(raw["balance_native"] * native_price, 2)

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
    async def get_wallet_portfolio(address: str, chain: str = "ethereum") -> str:
        """Get full wallet portfolio: native balance + all ERC-20 tokens with USD values.

        Combines native balance (via RPC), token balances (via Alchemy), and prices
        (via CoinGecko) into a single response with total portfolio value in USD.
        Token balances require ALCHEMY_API_KEY; without it only native balance is returned.

        Args:
            address: Wallet address (0x...).
            chain: "ethereum", "base", "arbitrum", "polygon", or "optimism".

        Returns:
            JSON object with native balance, token list with USD values, and total_value_usd.

        Examples:
            Full portfolio on Ethereum:
                Input: {"address": "0xd8dA6BF26964aF9D7eEd9e03E53415D37aA96045", "chain": "ethereum"}
                Output: {"address": "0xd8dA...", "chain": "ethereum", "native_symbol": "ETH", "native_balance": 32.5, "native_price_usd": 3150.0, "native_value_usd": 102375.0, "tokens": [{"symbol": "USDC", "name": "USD Coin", "balance": 50000.0, "price_usd": 1.0, "value_usd": 50000.0}, {"symbol": "AAVE", "name": "Aave", "balance": 15.2, "price_usd": 285.0, "value_usd": 4332.0}], "total_value_usd": 156707.0}

            Portfolio on Arbitrum:
                Input: {"address": "0xd8dA6BF26964aF9D7eEd9e03E53415D37aA96045", "chain": "arbitrum"}
                Output: {"address": "0xd8dA...", "chain": "arbitrum", "native_symbol": "ETH", "native_balance": 5.0, "native_price_usd": 3150.0, "native_value_usd": 15750.0, "tokens": [{"symbol": "ARB", "name": "Arbitrum", "balance": 1200.0, "price_usd": 1.85, "value_usd": 2220.0}], "total_value_usd": 17970.0}
        """
        cache_key = f"portfolio:{chain}:{address}"
        cached = cache.get(cache_key)
        if cached is not None:
            return cached

        # 1. Native balance (RPC — always works, no key needed)
        native_raw = await rpc.fetch_balance(address, chain)
        native_balance = native_raw["balance_native"]
        native_symbol = rpc.CHAIN_NATIVE_SYMBOL.get(chain.lower(), "ETH")

        # 2. Token balances (Alchemy — needs key)
        tokens_raw: list[dict] = []
        if settings.alchemy_api_key:
            try:
                tokens_raw = await alchemy.fetch_token_balances(address, chain)
            except Exception as exc:
                log.warning("Alchemy token balances failed for %s on %s: %s", address, chain, exc)

        # 3. Collect symbols for batch price lookup
        symbols_to_price = [native_symbol]
        for t in tokens_raw:
            sym = t.get("symbol")
            if sym:
                symbols_to_price.append(sym)

        # Deduplicate while preserving order
        seen = set()
        unique_symbols = []
        for s in symbols_to_price:
            up = s.upper()
            if up not in seen:
                seen.add(up)
                unique_symbols.append(s)

        # 4. Batch price fetch (CoinGecko)
        prices: dict[str, float] = {}
        try:
            price_data = await coingecko.fetch_prices(unique_symbols)
            for p in price_data:
                prices[p["symbol"].upper()] = p["price_usd"]
        except Exception as exc:
            log.warning("Price fetch failed for portfolio: %s", exc)

        # 5. Build portfolio
        native_price = prices.get(native_symbol.upper())
        native_value = round(native_balance * native_price, 2) if native_price and native_balance > 0 else None

        total_usd = native_value or 0.0

        portfolio_tokens = []
        for t in tokens_raw:
            sym = t.get("symbol") or "UNKNOWN"
            balance = t["balance"]
            price = prices.get(sym.upper())
            value = round(balance * price, 2) if price else None
            if value:
                total_usd += value
            portfolio_tokens.append(
                PortfolioToken(
                    symbol=sym,
                    name=t.get("name"),
                    balance=balance,
                    price_usd=price,
                    value_usd=value,
                ).model_dump()
            )

        # Sort tokens by USD value descending (tokens without price go last)
        portfolio_tokens.sort(key=lambda x: x.get("value_usd") or 0, reverse=True)

        portfolio = WalletPortfolio(
            address=address,
            chain=chain.lower(),
            native_symbol=native_symbol,
            native_balance=native_balance,
            native_price_usd=native_price,
            native_value_usd=native_value,
            tokens=portfolio_tokens,
            total_value_usd=round(total_usd, 2) if total_usd > 0 else None,
        ).model_dump()

        result = json.dumps(portfolio, ensure_ascii=False)
        cache.set(cache_key, result, settings.cache_ttl_portfolio)
        return result

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

        Examples:
            Recent USDC/USDT transfers on Ethereum:
                Input: {"address": "0xd8dA6BF26964aF9D7eEd9e03E53415D37aA96045", "chain": "ethereum", "limit": 5}
                Output: [{"tx_hash": "0xabc...", "block_number": 19500000, "timestamp": "2026-02-10T14:30:00Z", "from_address": "0xd8dA...", "to_address": "0x1234...", "token_symbol": "USDC", "value": "5000.0"}]
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

        Examples:
            Last 3 transactions on Ethereum:
                Input: {"address": "0xd8dA6BF26964aF9D7eEd9e03E53415D37aA96045", "chain": "ethereum", "limit": 3}
                Output: [{"tx_hash": "0xdef...", "block_number": 19500100, "timestamp": "2026-02-10T15:00:00Z", "from_address": "0xd8dA...", "to_address": "0x5678...", "value_eth": 0.5, "gas_used": 21000, "gas_price_gwei": 25.0, "status": "success"}]
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

        Examples:
            All tokens on Ethereum:
                Input: {"address": "0xd8dA6BF26964aF9D7eEd9e03E53415D37aA96045", "chain": "ethereum"}
                Output: [{"contract_address": "0xA0b8...", "symbol": "USDC", "name": "USD Coin", "balance": "15000.0", "decimals": 6}, {"contract_address": "0xdAC1...", "symbol": "USDT", "name": "Tether USD", "balance": "8500.0", "decimals": 6}]
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
