"""Smoke coverage for Jupiter Earn provider gateway routing."""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agent_wallet import providers  # noqa: E402
from agent_wallet.providers import jupiter  # noqa: E402


async def main() -> None:
    original_env = {
        "PROVIDER_GATEWAY_URL": os.environ.get("PROVIDER_GATEWAY_URL"),
        "PROVIDER_GATEWAY_BEARER_TOKEN": os.environ.get("PROVIDER_GATEWAY_BEARER_TOKEN"),
        "JUPITER_API_KEY": os.environ.get("JUPITER_API_KEY"),
    }
    original_get_client = jupiter.get_client

    seen: list[tuple[str, str, str | None]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append((request.method, str(request.url), request.headers.get("authorization")))
        if request.url.path.endswith("/v1/jupiter/earn/tokens"):
            return httpx.Response(200, json=[{"asset": "So111", "symbol": "SOL"}])
        if request.url.path.endswith("/v1/jupiter/earn/positions"):
            assert request.url.params["users"] == "wallet-a,wallet-b"
            return httpx.Response(
                200,
                json={"positions": [{"user": "wallet-a", "address": "position-a"}]},
            )
        if request.url.path.endswith("/v1/jupiter/earn/earnings"):
            assert request.url.params["user"] == "wallet-a"
            assert request.url.params["positions"] == "position-a,position-b"
            return httpx.Response(
                200,
                json={"earnings": [{"position": "position-a", "amountUsd": 1.23}]},
            )
        if request.url.path.endswith("/v1/jupiter/earn/deposit"):
            body = json.loads(request.content.decode())
            assert body == {"asset": "So111", "signer": "wallet-a", "amount": "1000"}
            return httpx.Response(200, json={"transaction": "deposit-tx"})
        if request.url.path.endswith("/v1/jupiter/earn/withdraw"):
            body = json.loads(request.content.decode())
            assert body == {"asset": "So111", "signer": "wallet-a", "amount": "500"}
            return httpx.Response(200, json={"transaction": "withdraw-tx"})
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))

    try:
        os.environ["PROVIDER_GATEWAY_URL"] = "https://gateway.example"
        os.environ["PROVIDER_GATEWAY_BEARER_TOKEN"] = "gateway-token"
        os.environ.pop("JUPITER_API_KEY", None)
        jupiter.get_client = lambda: client
        providers.jupiter.get_client = jupiter.get_client

        tokens = await jupiter.fetch_earn_tokens()
        assert tokens["tokens"][0]["symbol"] == "SOL"

        positions = await jupiter.fetch_earn_positions(users=["wallet-a", "wallet-b"])
        assert positions["positions"][0]["address"] == "position-a"

        earnings = await jupiter.fetch_earn_earnings(
            user="wallet-a",
            positions=["position-a", "position-b"],
        )
        assert earnings["earnings"][0]["amountUsd"] == 1.23

        deposit = await jupiter.build_earn_deposit_transaction(
            asset="So111",
            user_address="wallet-a",
            amount_raw="1000",
        )
        assert deposit["transaction"] == "deposit-tx"

        withdraw = await jupiter.build_earn_withdraw_transaction(
            asset="So111",
            user_address="wallet-a",
            amount_raw="500",
        )
        assert withdraw["transaction"] == "withdraw-tx"

        assert all(item[2] == "Bearer gateway-token" for item in seen)
        print("smoke_jupiter_earn_provider_gateway: ok")
    finally:
        jupiter.get_client = original_get_client
        providers.jupiter.get_client = original_get_client
        await client.aclose()
        for key, value in original_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


if __name__ == "__main__":
    asyncio.run(main())
