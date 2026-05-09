"""Smoke test for the Houdini provider client without real network access."""

from __future__ import annotations

import asyncio
import sys
from decimal import Decimal
from pathlib import Path
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agent_wallet.config import settings
from agent_wallet.providers import houdini


class FakeResponse:
    def __init__(self, status_code: int, payload: dict):
        self.status_code = status_code
        self._payload = payload
        self.content = b"{}"

    def json(self) -> dict:
        return self._payload


class FakeClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, dict | None, dict | None, dict]] = []

    async def get(self, url: str, *, params=None, headers=None):
        self.calls.append(("GET", url, params, None, headers or {}))
        path = urlparse(url).path
        if path.endswith("/tokens"):
            return FakeResponse(
                200,
                {
                    "tokens": [
                        {
                            "id": "sol-token-id",
                            "symbol": "SOL",
                            "name": "Solana",
                            "address": "11111111111111111111111111111111",
                            "chain": "solana",
                            "decimals": 9,
                            "hasCex": True,
                            "enabled": True,
                            "minMax": {"private": {"min": 0.01, "max": 50}},
                        },
                        {
                            "id": "sol-token-id-duplicate",
                            "symbol": "SOL",
                            "name": "Solana Duplicate",
                            "address": "So11111111111111111111111111111111111111112",
                            "chain": "solana",
                            "decimals": 9,
                            "hasCex": True,
                            "enabled": True,
                            "minMax": {"private": {"min": 0.01, "max": 50}},
                        },
                        {
                            "id": "usdc-token-id",
                            "symbol": "USDC",
                            "name": "USD Coin",
                            "address": "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
                            "chain": "solana",
                            "decimals": 6,
                            "hasCex": True,
                            "enabled": True,
                            "minMax": {"private": {"min": 1, "max": 100000}},
                        },
                    ],
                    "totalPages": 1,
                },
            )
        if path.endswith("/quotes"):
            return FakeResponse(
                200,
                {
                    "quotes": [
                        {
                            "quoteId": "private-quote-1",
                            "type": "private",
                            "amountIn": 0.1,
                            "amountOut": 0.0985,
                            "amountOutUsd": 19.7,
                            "duration": 28,
                            "rewardsAvailable": False,
                        },
                        {
                            "quoteId": "standard-quote-1",
                            "type": "standard",
                            "amountIn": 0.1,
                            "amountOut": 0.099,
                            "duration": 5,
                        },
                    ]
                },
            )
        if "/orders/" in path:
            return FakeResponse(
                200,
                {
                    "houdiniId": "houdini_fake_1",
                    "statusLabel": "WAITING",
                    "depositAddress": "Deposit11111111111111111111111111111111111",
                    "receiverAddress": "FakeRecipient1111111111111111111111111111111111",
                    "anonymous": True,
                    "from": "sol-token-id",
                    "to": "sol-token-id",
                    "inAmount": "0.1",
                    "outAmount": "0.0985",
                },
            )
        if "/exchanges/multi/" in path and path.endswith("/tx"):
            parsed = parse_qs(urlparse(url).query)
            sender = (params or {}).get("sender") or parsed.get("sender", [""])[0]
            assert sender == "FakeSender1111111111111111111111111111111111"
            return FakeResponse(
                200,
                {
                    "multiId": "multi_fake_1",
                    "chain": "solana",
                    "transactions": [
                        {
                            "houdiniIds": ["houdini_fake_1"],
                            "txData": {"data": "ZmFrZS10eA=="},
                        }
                    ],
                },
            )
        if "/exchanges/multi/" in path:
            return FakeResponse(
                200,
                {
                    "multiId": "multi_fake_1",
                    "orders": [
                        {
                            "houdiniId": "houdini_fake_1",
                            "multiId": "multi_fake_1",
                            "statusLabel": "WAITING",
                            "receiverAddress": "FakeRecipient1111111111111111111111111111111111",
                        }
                    ],
                },
            )
        raise AssertionError(f"Unexpected GET path: {path}")

    async def post(self, url: str, *, json=None, headers=None):
        self.calls.append(("POST", url, None, json, headers or {}))
        path = urlparse(url).path
        if path.endswith("/exchanges"):
            return FakeResponse(
                200,
                {
                    "houdiniId": "houdini_fake_1",
                    "statusLabel": "NEW",
                    "depositAddress": "Deposit11111111111111111111111111111111111",
                    "receiverAddress": "FakeRecipient1111111111111111111111111111111111",
                    "anonymous": True,
                    "from": "sol-token-id",
                    "to": "sol-token-id",
                    "inAmount": "0.1",
                    "outAmount": "0.0985",
                },
            )
        if path.endswith("/exchanges/multi"):
            return FakeResponse(
                200,
                {
                    "multiId": "multi_fake_1",
                    "orders": [
                        {
                            "order": {
                                "houdiniId": "houdini_fake_1",
                                "multiId": "multi_fake_1",
                                "depositAddress": "Deposit11111111111111111111111111111111111",
                                "receiverAddress": "FakeRecipient1111111111111111111111111111111111",
                                "anonymous": True,
                                "statusLabel": "NEW",
                                "inAmount": 0.1,
                                "inSymbol": "SOL",
                                "outAmount": 0.0985,
                                "outSymbol": "SOL",
                                "eta": 28,
                            }
                        }
                    ],
                },
            )
        raise AssertionError(f"Unexpected POST path: {path}")


async def main() -> None:
    original_values = {
        "houdini_api_base_url": settings.houdini_api_base_url,
        "houdini_api_key": settings.houdini_api_key,
        "houdini_api_secret": settings.houdini_api_secret,
        "houdini_user_ip": settings.houdini_user_ip,
        "houdini_user_agent": settings.houdini_user_agent,
        "houdini_user_timezone": settings.houdini_user_timezone,
        "provider_gateway_url": settings.provider_gateway_url,
        "provider_gateway_bearer_token": settings.provider_gateway_bearer_token,
    }
    original_get_client = houdini.get_client
    fake_client = FakeClient()
    try:
        settings.houdini_api_base_url = "https://api-partner.houdiniswap.com/v2"
        settings.houdini_api_key = "key"
        settings.houdini_api_secret = "secret"
        settings.houdini_user_ip = "127.0.0.1"
        settings.houdini_user_agent = "AgentLayerSmoke/1.0"
        settings.houdini_user_timezone = "Europe/Moscow"
        settings.provider_gateway_url = ""
        settings.provider_gateway_bearer_token = ""
        houdini._CEX_TOKEN_CACHE.clear()
        houdini.get_client = lambda: fake_client

        tokens = await houdini.fetch_cex_tokens(chain="solana")
        assert len(tokens) == 3
        sol = await houdini.resolve_cex_token(term="SOL", chain="solana")
        assert sol["id"] == "sol-token-id"
        usdc = await houdini.resolve_cex_token(
            term="EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
            chain="solana",
        )
        assert usdc["symbol"] == "USDC"

        quotes = await houdini.fetch_private_quotes(
            from_token_id="sol-token-id",
            to_token_id="sol-token-id",
            amount_ui=Decimal("0.1"),
        )
        assert len(quotes) == 1
        best_quote = houdini.select_best_private_quote(quotes)
        assert best_quote["quoteId"] == "private-quote-1"

        exchange = await houdini.create_exchange(
            quote_id="private-quote-1",
            destination_address="FakeRecipient1111111111111111111111111111111111",
        )
        assert exchange["houdiniId"] == "houdini_fake_1"

        order = await houdini.fetch_order_status(houdini_id="houdini_fake_1")
        assert order["statusLabel"] == "WAITING"

        multi = await houdini.create_multi_swap(
            orders=[
                {
                    "from": "sol-token-id",
                    "to": "sol-token-id",
                    "amount": 0.1,
                    "addressTo": "FakeRecipient1111111111111111111111111111111111",
                    "anonymous": True,
                }
            ]
        )
        assert multi["multiId"] == "multi_fake_1"

        status = await houdini.fetch_multi_status(multi_id="multi_fake_1")
        assert status["orders"][0]["statusLabel"] == "WAITING"

        tx = await houdini.fetch_multi_solana_transactions(
            multi_id="multi_fake_1",
            sender="FakeSender1111111111111111111111111111111111",
        )
        assert tx["transactions"][0]["houdiniIds"] == ["houdini_fake_1"]

        for _, _, _, _, headers in fake_client.calls:
            assert headers["Authorization"] == "key:secret"
            assert headers["x-user-ip"] == "127.0.0.1"
            assert headers["x-user-agent"] == "AgentLayerSmoke/1.0"
            assert headers["x-user-timezone"] == "Europe/Moscow"
    finally:
        for key, value in original_values.items():
            setattr(settings, key, value)
        houdini.get_client = original_get_client
        houdini._CEX_TOKEN_CACHE.clear()

    print("smoke_houdini_provider: ok")


if __name__ == "__main__":
    asyncio.run(main())
