"""EVM portfolio helpers for token discovery and USD enrichment."""

from __future__ import annotations

import time
from decimal import Decimal, InvalidOperation
from typing import Any

from agent_wallet.config import settings
from agent_wallet.exceptions import ProviderError
from agent_wallet.http_client import get_client

COINGECKO_API_URL = "https://api.coingecko.com/api/v3"
PORTFOLIO_TOKEN_CACHE_TTL_SECONDS = 30.0
PORTFOLIO_PRICE_CACHE_TTL_SECONDS = 60.0

TOKEN_METADATA: dict[str, dict[str, dict[str, Any]]] = {
    "ethereum": {
        "0xdac17f958d2ee523a2206206994597c13d831ec7": {
            "symbol": "USDT",
            "name": "Tether USD",
            "decimals": 6,
        },
        "0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48": {
            "symbol": "USDC",
            "name": "USD Coin",
            "decimals": 6,
        },
        "0x6b175474e89094c44da98b954eedeac495271d0f": {
            "symbol": "DAI",
            "name": "Dai",
            "decimals": 18,
        },
        "0x2260fac5e5542a773aa44fbcfedf7c193bc2c599": {
            "symbol": "WBTC",
            "name": "Wrapped BTC",
            "decimals": 8,
        },
        "0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2": {
            "symbol": "WETH",
            "name": "Wrapped Ether",
            "decimals": 18,
        },
        "0x7f39c581f595b53c5cb19bd0b3f8da6c935e2ca0": {
            "symbol": "wstETH",
            "name": "Wrapped stETH",
            "decimals": 18,
        },
        "0xae78736cd615f374d3085123a210448e74fc6393": {
            "symbol": "rETH",
            "name": "Rocket Pool ETH",
            "decimals": 18,
        },
        "0x514910771af9ca656af840dff83e8264ecf986ca": {
            "symbol": "LINK",
            "name": "Chainlink",
            "decimals": 18,
        },
        "0x1f9840a85d5af5bf1d1762f925bdaddc4201f984": {
            "symbol": "UNI",
            "name": "Uniswap",
            "decimals": 18,
        },
        "0x7fc66500c84a76ad7e9c93437bfc5ac33e2ddae9": {
            "symbol": "AAVE",
            "name": "Aave",
            "decimals": 18,
        },
        "0x9f8f72aa9304c8b593d555f12ef6589cc3a579a2": {
            "symbol": "MKR",
            "name": "Maker",
            "decimals": 18,
        },
        "0x5a98fcbea516cf06857215779fd812ca3bef1b32": {
            "symbol": "LDO",
            "name": "Lido DAO",
            "decimals": 18,
        },
        "0xd533a949740bb3306d119cc777fa900ba034cd52": {
            "symbol": "CRV",
            "name": "Curve DAO Token",
            "decimals": 18,
        },
        "0x95ad61b0a150d79219dcf64e1e6cc01f0b64c4ce": {
            "symbol": "SHIB",
            "name": "Shiba Inu",
            "decimals": 18,
        },
        "0x6982508145454ce325ddbe47a25d4ec3d2311933": {
            "symbol": "PEPE",
            "name": "Pepe",
            "decimals": 18,
        },
    },
    "base": {
        "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913": {
            "symbol": "USDC",
            "name": "USD Coin",
            "decimals": 6,
        },
        "0x50c5725949a6f0c72e6c4a641f24049a917db0cb": {
            "symbol": "DAI",
            "name": "Dai",
            "decimals": 18,
        },
        "0x4200000000000000000000000000000000000006": {
            "symbol": "WETH",
            "name": "Wrapped Ether",
            "decimals": 18,
        },
        "0x2ae3f1ec7f1f5012cfeab0185bfc7aa3cf0dec22": {
            "symbol": "cbETH",
            "name": "Coinbase Wrapped Staked ETH",
            "decimals": 18,
        },
    },
}

COINGECKO_IDS = {
    "ETH": "ethereum",
    "WETH": "ethereum",
    "USDC": "usd-coin",
    "USDT": "tether",
    "DAI": "dai",
    "WBTC": "wrapped-bitcoin",
    "LINK": "chainlink",
    "UNI": "uniswap",
    "AAVE": "aave",
    "MKR": "maker",
    "LDO": "lido-dao",
    "CRV": "curve-dao-token",
    "SHIB": "shiba-inu",
    "PEPE": "pepe",
    "RETH": "rocket-pool-eth",
    "CBETH": "coinbase-wrapped-staked-eth",
    "WSTETH": "wrapped-steth",
}

_TOKEN_CACHE: dict[str, tuple[float, list[dict[str, Any]]]] = {}
_PRICE_CACHE: dict[str, tuple[float, float]] = {}


def _normalize_network(network: str) -> str:
    normalized = str(network or "").strip().lower()
    if normalized not in {"ethereum", "base", "robinhood"}:
        raise ProviderError("evm-portfolio", f"Unsupported EVM portfolio network: {network}")
    return normalized


def _cache_get_token_balances(cache_key: str) -> list[dict[str, Any]] | None:
    cached = _TOKEN_CACHE.get(cache_key)
    if not cached:
        return None
    expires_at, payload = cached
    if expires_at <= time.time():
        _TOKEN_CACHE.pop(cache_key, None)
        return None
    return payload


def _cache_set_token_balances(cache_key: str, payload: list[dict[str, Any]]) -> None:
    _TOKEN_CACHE[cache_key] = (time.time() + PORTFOLIO_TOKEN_CACHE_TTL_SECONDS, payload)


def _cache_get_price(symbol: str) -> float | None:
    cached = _PRICE_CACHE.get(symbol.upper())
    if not cached:
        return None
    expires_at, price = cached
    if expires_at <= time.time():
        _PRICE_CACHE.pop(symbol.upper(), None)
        return None
    return price


def _cache_set_price(symbol: str, price: float) -> None:
    _PRICE_CACHE[symbol.upper()] = (time.time() + PORTFOLIO_PRICE_CACHE_TTL_SECONDS, price)


def _format_decimal(value: Decimal | None, *, places: int | None = None) -> str | None:
    if value is None:
        return None
    normalized = value
    if places is not None:
        quant = Decimal("1").scaleb(-places)
        normalized = value.quantize(quant)
    text = format(normalized.normalize(), "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"


def _to_decimal(value: Any) -> Decimal | None:
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


async def _gateway_rpc_call(network: str, method: str, params: list[Any]) -> dict[str, Any]:
    client = get_client()
    payload = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}
    gateway_url = str(settings.provider_gateway_url or "").strip()
    bearer = str(settings.provider_gateway_bearer_token or "").strip()
    if not gateway_url:
        raise ProviderError(
            "evm-portfolio",
            "Provider gateway URL is required for EVM portfolio lookup on ethereum/base/robinhood.",
        )
    try:
        response = await client.post(
            f"{gateway_url.rstrip('/')}/v1/evm/rpc/{network}?provider=alchemy",
            json=payload,
            headers={"Authorization": f"Bearer {bearer}"} if bearer else None,
        )
    except Exception as exc:  # pragma: no cover - network path
        raise ProviderError("evm-portfolio", f"Provider gateway request failed: {exc}") from exc
    if response.status_code != 200:
        raise ProviderError(
            "evm-portfolio",
            f"Provider gateway returned HTTP {response.status_code} for {method}.",
        )
    data = response.json()
    if "error" in data:
        raise ProviderError("evm-portfolio", f"Provider gateway RPC error: {data['error']}")
    return data


async def fetch_token_balances(address: str, network: str) -> list[dict[str, Any]]:
    normalized_network = _normalize_network(network)
    cache_key = f"{normalized_network}:{address.lower()}"
    cached = _cache_get_token_balances(cache_key)
    if cached is not None:
        return cached

    data = await _gateway_rpc_call(
        normalized_network,
        "alchemy_getTokenBalances",
        [address, "erc20"],
    )
    balances = []
    metadata_by_address = TOKEN_METADATA.get(normalized_network, {})
    token_balances = list((data.get("result") or {}).get("tokenBalances") or [])
    for item in token_balances:
        contract = str(item.get("contractAddress") or "").strip()
        raw_hex = str(item.get("tokenBalance") or "").strip().lower()
        if not contract or raw_hex in {"", "0x", "0x0"}:
            continue
        try:
            balance_raw = int(raw_hex, 16)
        except ValueError:
            continue
        if balance_raw <= 0:
            continue
        known = metadata_by_address.get(contract.lower()) or {}
        decimals = known.get("decimals")
        balance_ui = None
        if isinstance(decimals, int) and decimals >= 0:
            balance_ui = Decimal(balance_raw) / (Decimal(10) ** decimals)
        balances.append(
            {
                "contract_address": contract,
                "symbol": known.get("symbol"),
                "name": known.get("name"),
                "decimals": decimals,
                "balance_raw": str(balance_raw),
                "balance_ui": _format_decimal(balance_ui) if balance_ui is not None else None,
                "verified": bool(known),
                "source": "alchemy_getTokenBalances",
            }
        )

    balances.sort(
        key=lambda item: (
            item.get("balance_ui") is None,
            -(Decimal(item["balance_ui"]) if item.get("balance_ui") is not None else Decimal(0)),
        )
    )
    _cache_set_token_balances(cache_key, balances)
    return balances


async def fetch_usd_prices(symbols: list[str]) -> dict[str, float]:
    normalized_symbols = []
    seen: set[str] = set()
    prices: dict[str, float] = {}
    for symbol in symbols:
        normalized = str(symbol or "").strip().upper()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        cached = _cache_get_price(normalized)
        if cached is not None:
            prices[normalized] = cached
            continue
        if normalized in COINGECKO_IDS:
            normalized_symbols.append(normalized)

    if not normalized_symbols:
        return prices

    ids = [COINGECKO_IDS[symbol] for symbol in normalized_symbols]
    client = get_client()
    try:
        response = await client.get(
            f"{COINGECKO_API_URL}/simple/price",
            params={
                "ids": ",".join(ids),
                "vs_currencies": "usd",
            },
        )
    except Exception as exc:  # pragma: no cover - network path
        raise ProviderError("evm-portfolio", f"CoinGecko request failed: {exc}") from exc

    if response.status_code != 200:
        raise ProviderError("evm-portfolio", f"CoinGecko returned HTTP {response.status_code}.")

    payload = response.json()
    for symbol in normalized_symbols:
        cg_id = COINGECKO_IDS[symbol]
        usd_value = payload.get(cg_id, {}).get("usd")
        if usd_value is None:
            continue
        price = float(usd_value)
        prices[symbol] = price
        _cache_set_price(symbol, price)
    return prices


async def build_portfolio_snapshot(
    *,
    address: str,
    network: str,
    native_symbol: str,
    native_balance_wei: str,
    native_balance: str,
) -> dict[str, Any]:
    normalized_network = _normalize_network(network)
    tokens = await fetch_token_balances(address, normalized_network)
    symbols = [native_symbol] + [
        str(token.get("symbol") or "").strip()
        for token in tokens
        if str(token.get("symbol") or "").strip()
    ]
    prices = await fetch_usd_prices(symbols)

    native_balance_decimal = _to_decimal(native_balance) or Decimal(0)
    native_price_usd = prices.get(str(native_symbol or "").upper())
    native_value_usd = (
        native_balance_decimal * Decimal(str(native_price_usd))
        if native_price_usd is not None and native_balance_decimal > 0
        else None
    )

    portfolio_tokens: list[dict[str, Any]] = []
    total_value = native_value_usd or Decimal(0)

    for token in tokens:
        symbol = str(token.get("symbol") or "").strip().upper()
        balance_ui_decimal = _to_decimal(token.get("balance_ui"))
        price_usd = prices.get(symbol) if symbol else None
        value_usd = (
            balance_ui_decimal * Decimal(str(price_usd))
            if price_usd is not None and balance_ui_decimal is not None and balance_ui_decimal > 0
            else None
        )
        if value_usd is not None:
            total_value += value_usd
        portfolio_tokens.append(
            {
                "token_address": token["contract_address"],
                "balance_raw": token["balance_raw"],
                "balance_ui": token.get("balance_ui"),
                "token_metadata": {
                    "address": token["contract_address"],
                    "name": token.get("name"),
                    "symbol": token.get("symbol"),
                    "decimals": token.get("decimals"),
                    "verified": bool(token.get("verified")),
                    "source": token.get("source") or "alchemy_getTokenBalances",
                },
                "price_usd": _format_decimal(Decimal(str(price_usd)), places=6) if price_usd is not None else None,
                "value_usd": _format_decimal(value_usd, places=2),
            }
        )

    portfolio_tokens.sort(
        key=lambda item: _to_decimal(item.get("value_usd")) or Decimal("-1"),
        reverse=True,
    )

    native_asset = {
        "asset_type": "native",
        "symbol": native_symbol,
        "amount_raw": str(native_balance_wei),
        "amount_ui": str(native_balance),
        "price_usd": _format_decimal(Decimal(str(native_price_usd)), places=6)
        if native_price_usd is not None
        else None,
        "value_usd": _format_decimal(native_value_usd, places=2),
        "pricing_source": "coingecko" if native_price_usd is not None else None,
    }
    assets = [native_asset]
    assets.extend(
        {
            "asset_type": "erc20",
            "token_address": token.get("token_address"),
            "symbol": (token.get("token_metadata") or {}).get("symbol"),
            "amount_raw": token.get("balance_raw"),
            "amount_ui": token.get("balance_ui"),
            "decimals": (token.get("token_metadata") or {}).get("decimals"),
            "price_usd": token.get("price_usd"),
            "value_usd": token.get("value_usd"),
            "pricing_source": "coingecko" if token.get("price_usd") is not None else None,
        }
        for token in portfolio_tokens
    )
    assets.sort(
        key=lambda item: _to_decimal(item.get("value_usd")) or Decimal("-1"),
        reverse=True,
    )
    priced_asset_count = sum(1 for asset in assets if asset.get("value_usd") is not None)
    formatted_total_value = _format_decimal(total_value, places=2) if total_value > 0 else None

    return {
        "address": address,
        "network": normalized_network,
        "asset": native_symbol,
        "balance_wei": str(native_balance_wei),
        "balance_native": str(native_balance),
        "native_price_usd": _format_decimal(Decimal(str(native_price_usd)), places=6)
        if native_price_usd is not None
        else None,
        "native_value_usd": _format_decimal(native_value_usd, places=2),
        "tokens": portfolio_tokens,
        "token_count": len(portfolio_tokens),
        "assets": assets,
        "asset_count": len(assets),
        "priced_asset_count": priced_asset_count,
        "balance_usd": formatted_total_value,
        "total_value_usd": formatted_total_value,
        "pricing_source": "coingecko",
        "token_discovery_source": "alchemy_getTokenBalances",
    }
