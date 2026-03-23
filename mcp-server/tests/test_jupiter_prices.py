import asyncio
import json
import sys
from types import SimpleNamespace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from cache import Cache
from providers import jupiter
from tools import prices


class FakeResponse:
    def __init__(self, status_code: int, payload):
        self.status_code = status_code
        self._payload = payload
        self.text = json.dumps(payload)

    def json(self):
        return self._payload


class FakeClient:
    def __init__(self):
        self.calls: list[tuple[str, dict | None, dict | None]] = []

    async def get(self, url, params=None, headers=None):
        self.calls.append((url, params, headers))

        if url.endswith("/tokens/v2/search"):
            query = (params or {}).get("query")
            if query == "JUP":
                return FakeResponse(
                    200,
                    [
                        {
                            "id": "JUPyiwrYJFskUPiHa7hkeR8VUtAeFoSYbKedZNsDvCN",
                            "name": "Jupiter",
                            "symbol": "JUP",
                            "decimals": 6,
                            "mcap": 459171256.1,
                            "liquidity": 2992387.89,
                            "organicScore": 97.98,
                            "isVerified": True,
                            "priceBlockId": 402118601,
                            "stats24h": {
                                "priceChange": -8.27,
                                "buyVolume": 1821969.64,
                                "sellVolume": 2016195.15,
                            },
                        }
                    ],
                )
            if query == "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v":
                return FakeResponse(
                    200,
                    [
                        {
                            "id": "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
                            "name": "USD Coin",
                            "symbol": "USDC",
                            "decimals": 6,
                            "mcap": 0,
                            "liquidity": 1000000,
                            "organicScore": 90,
                            "isVerified": True,
                            "priceBlockId": 402118602,
                            "stats24h": {
                                "priceChange": 0.01,
                                "buyVolume": 500000,
                                "sellVolume": 600000,
                            },
                        }
                    ],
                )
            raise AssertionError(f"Unexpected token search query: {query}")

        if url.endswith("/price/v3"):
            ids = (params or {}).get("ids")
            if ids == (
                "JUPyiwrYJFskUPiHa7hkeR8VUtAeFoSYbKedZNsDvCN,"
                "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
            ):
                return FakeResponse(
                    200,
                    {
                        "JUPyiwrYJFskUPiHa7hkeR8VUtAeFoSYbKedZNsDvCN": {
                            "usdPrice": 0.1415,
                            "priceChange24h": -8.27,
                            "blockId": 402118601,
                        },
                        "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v": {
                            "usdPrice": 1.0,
                            "priceChange24h": 0.01,
                            "blockId": 402118602,
                        },
                    },
                )
            raise AssertionError(f"Unexpected price ids: {ids}")

        raise AssertionError(f"Unexpected URL: {url}")


class FakeMCP:
    def __init__(self):
        self.tools = {}

    def tool(self):
        def decorator(fn):
            self.tools[fn.__name__] = fn
            return fn

        return decorator


def test_jupiter_provider_fetch_prices(monkeypatch):
    fake_client = FakeClient()
    monkeypatch.setattr(jupiter.settings, "jupiter_api_key", "test-key")
    monkeypatch.setattr(jupiter, "get_client", lambda: fake_client)

    result = asyncio.run(
        jupiter.fetch_prices(
            [
                "JUP",
                "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
            ]
        )
    )

    assert len(result) == 2
    assert result[0]["symbol"] == "JUP"
    assert result[0]["mint"] == "JUPyiwrYJFskUPiHa7hkeR8VUtAeFoSYbKedZNsDvCN"
    assert result[0]["price_usd"] == 0.1415
    assert result[0]["verified"] is True
    assert result[0]["liquidity_usd"] == 2992387.89
    assert result[1]["symbol"] == "USDC"
    assert result[1]["price_usd"] == 1.0
    assert fake_client.calls[0][2] == {"x-api-key": "test-key"}


def test_get_solana_token_prices_uses_cache(monkeypatch):
    fetch_calls = {"count": 0}

    async def fake_fetch_prices(assets):
        fetch_calls["count"] += 1
        assert assets == ["JUP"]
        return [
            {
                "asset_id": "JUP",
                "mint": "JUPyiwrYJFskUPiHa7hkeR8VUtAeFoSYbKedZNsDvCN",
                "symbol": "JUP",
                "name": "Jupiter",
                "price_usd": 0.1415,
                "change_24h": -8.27,
                "volume_24h": 3838164.79,
                "market_cap": 459171256.1,
                "decimals": 6,
                "block_id": 402118601,
                "liquidity_usd": 2992387.89,
                "verified": True,
                "organic_score": 97.98,
                "source": "jupiter",
            }
        ]

    fake_mcp = FakeMCP()
    cache = Cache()
    monkeypatch.setattr(prices, "_jupiter", SimpleNamespace(fetch_prices=fake_fetch_prices))

    prices.register(fake_mcp, cache)
    tool = fake_mcp.tools["get_solana_token_prices"]

    first = asyncio.run(tool(["JUP"]))
    second = asyncio.run(tool(["JUP"]))

    payload = json.loads(first)
    assert payload[0]["symbol"] == "JUP"
    assert payload[0]["source"] == "jupiter"
    assert first == second
    assert fetch_calls["count"] == 1


def test_get_crypto_prices_falls_back_to_jupiter(monkeypatch):
    async def fake_coingecko(symbols):
        assert symbols == ["JUP"]
        return []

    async def fake_coincap(symbols):
        assert symbols == ["JUP"]
        return []

    async def fake_jupiter(symbols):
        assert symbols == ["JUP"]
        return [
            {
                "asset_id": "JUP",
                "mint": "JUPyiwrYJFskUPiHa7hkeR8VUtAeFoSYbKedZNsDvCN",
                "symbol": "JUP",
                "name": "Jupiter",
                "price_usd": 0.1415,
                "change_24h": -8.27,
                "volume_24h": 3838164.79,
                "market_cap": 459171256.1,
                "decimals": 6,
                "block_id": 402118601,
                "liquidity_usd": 2992387.89,
                "verified": True,
                "organic_score": 97.98,
                "source": "jupiter",
            }
        ]

    async def unexpected_dexscreener(_symbols):
        raise AssertionError("DexScreener should not be called when Jupiter resolves the asset")

    fake_mcp = FakeMCP()
    cache = Cache()

    monkeypatch.setattr(prices.coingecko, "fetch_prices", fake_coingecko)
    monkeypatch.setattr(prices, "_coincap", SimpleNamespace(fetch_prices=fake_coincap))
    monkeypatch.setattr(prices, "_jupiter", SimpleNamespace(fetch_prices=fake_jupiter))
    monkeypatch.setattr(prices, "_dexscreener", SimpleNamespace(fetch_prices=unexpected_dexscreener))

    prices.register(fake_mcp, cache)
    tool = fake_mcp.tools["get_crypto_prices"]

    result = asyncio.run(tool(["JUP"]))
    payload = json.loads(result)

    assert len(payload) == 1
    assert payload[0]["symbol"] == "JUP"
    assert payload[0]["source"] == "jupiter"
    assert payload[0]["mint"] == "JUPyiwrYJFskUPiHa7hkeR8VUtAeFoSYbKedZNsDvCN"
