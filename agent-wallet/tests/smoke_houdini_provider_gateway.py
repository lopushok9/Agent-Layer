"""Smoke test for Houdini provider routing through provider-gateway."""

from __future__ import annotations

import asyncio
import json
import sys
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agent_wallet.config import settings
from agent_wallet.providers import houdini


class FakeResponse:
    def __init__(self, status_code: int, payload: dict):
        self.status_code = status_code
        self._payload = payload
        self.text = json.dumps(payload)
        self.content = self.text.encode("utf-8")

    def json(self) -> dict:
        return self._payload


class FakeClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, dict | None, dict | None, dict]] = []

    async def get(self, url: str, *, params=None, headers=None):
        self.calls.append(("GET", url, params, None, headers or {}))
        if url.endswith("/v1/houdini/tokens"):
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
                        }
                    ],
                    "totalPages": 1,
                },
            )
        if url.endswith("/v1/houdini/quotes/private"):
            return FakeResponse(
                200,
                {
                    "quotes": [
                        {
                            "quoteId": "private-quote-1",
                            "type": "private",
                            "amountIn": 0.1,
                            "amountOut": 0.0985,
                            "duration": 28,
                        }
                    ]
                },
            )
        if url.endswith("/v1/houdini/orders/houdini_fake_1"):
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
        if url.endswith("/v1/houdini/exchanges/multi/multi_fake_1/tx"):
            return FakeResponse(
                200,
                {
                    "multiId": "multi_fake_1",
                    "transactions": [
                        {
                            "houdiniIds": ["houdini_fake_1"],
                            "txData": {"data": "ZmFrZS10eA=="},
                        }
                    ],
                },
            )
        if url.endswith("/v1/houdini/exchanges/multi/multi_fake_1"):
            return FakeResponse(
                200,
                {
                    "multiId": "multi_fake_1",
                    "orders": [
                        {
                            "houdiniId": "houdini_fake_1",
                            "multiId": "multi_fake_1",
                            "statusLabel": "WAITING",
                        }
                    ],
                },
            )
        raise AssertionError(f"Unexpected GET path: {url}")

    async def post(self, url: str, *, json=None, headers=None):
        self.calls.append(("POST", url, None, json, headers or {}))
        if url.endswith("/v1/houdini/exchanges"):
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
        if url.endswith("/v1/houdini/exchanges/multi"):
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
        raise AssertionError(f"Unexpected POST path: {url}")


async def main() -> None:
    original_values = {
        "houdini_api_key": settings.houdini_api_key,
        "houdini_api_secret": settings.houdini_api_secret,
        "houdini_user_agent": settings.houdini_user_agent,
        "houdini_user_timezone": settings.houdini_user_timezone,
        "provider_gateway_url": settings.provider_gateway_url,
        "provider_gateway_bearer_token": settings.provider_gateway_bearer_token,
    }
    original_get_client = houdini.get_client
    fake_client = FakeClient()
    try:
        settings.houdini_api_key = ""
        settings.houdini_api_secret = ""
        settings.houdini_user_agent = "AgentLayerSmoke/1.0"
        settings.houdini_user_timezone = "Europe/Moscow"
        settings.provider_gateway_url = "https://gateway.example"
        settings.provider_gateway_bearer_token = "gateway-token"
        houdini._CEX_TOKEN_CACHE.clear()
        houdini.get_client = lambda: fake_client

        tokens = await houdini.fetch_cex_tokens(chain="solana")
        assert len(tokens) == 1

        quotes = await houdini.fetch_private_quotes(
            from_token_id="sol-token-id",
            to_token_id="sol-token-id",
            amount_ui=Decimal("0.1"),
        )
        assert len(quotes) == 1

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

        exchange = await houdini.create_exchange(
            quote_id="private-quote-1",
            destination_address="FakeRecipient1111111111111111111111111111111111",
        )
        assert exchange["houdiniId"] == "houdini_fake_1"

        order = await houdini.fetch_order_status(houdini_id="houdini_fake_1")
        assert order["statusLabel"] == "WAITING"

        status = await houdini.fetch_multi_status(multi_id="multi_fake_1")
        assert status["orders"][0]["statusLabel"] == "WAITING"

        tx = await houdini.fetch_multi_solana_transactions(
            multi_id="multi_fake_1",
            sender="FakeSender1111111111111111111111111111111111",
        )
        assert tx["transactions"][0]["houdiniIds"] == ["houdini_fake_1"]

        for _, _, _, _, headers in fake_client.calls:
            assert headers["Authorization"] == "Bearer gateway-token"
            assert headers["x-user-agent"] == "AgentLayerSmoke/1.0"
            assert headers["x-user-timezone"] == "Europe/Moscow"
            assert "x-user-ip" not in headers
    finally:
        for key, value in original_values.items():
            setattr(settings, key, value)
        houdini.get_client = original_get_client
        houdini._CEX_TOKEN_CACHE.clear()

    print("smoke_houdini_provider_gateway: ok")


if __name__ == "__main__":
    asyncio.run(main())
