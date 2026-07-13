"""Smoke coverage for EVM portfolio routing through provider-gateway."""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agent_wallet.config import settings  # noqa: E402
from agent_wallet.providers import evm_portfolio  # noqa: E402


async def _run() -> None:
    original_values = {
        "provider_gateway_url": settings.provider_gateway_url,
        "provider_gateway_bearer_token": settings.provider_gateway_bearer_token,
    }
    original_get_client = evm_portfolio.get_client

    seen_urls: list[str] = []
    seen_auth: list[str | None] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_urls.append(str(request.url))
        seen_auth.append(request.headers.get("authorization"))
        assert request.url in {
            httpx.URL("https://gateway.example/v1/evm/rpc/base?provider=alchemy"),
            httpx.URL("https://gateway.example/v1/evm/rpc/robinhood?provider=alchemy"),
        }
        return httpx.Response(
            200,
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "result": {
                    "tokenBalances": [
                        {
                            "contractAddress": "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913",
                            "tokenBalance": "0x2a",
                        }
                    ]
                },
            },
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    try:
        settings.provider_gateway_url = "https://gateway.example"
        settings.provider_gateway_bearer_token = "gateway-token"
        evm_portfolio.get_client = lambda: client
        balances = await evm_portfolio.fetch_token_balances(
            "0x1111111111111111111111111111111111111111",
            "base",
        )
        assert len(balances) == 1
        assert balances[0]["contract_address"].lower() == "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913"
        assert seen_urls == ["https://gateway.example/v1/evm/rpc/base?provider=alchemy"]
        assert seen_auth == ["Bearer gateway-token"]
        balances = await evm_portfolio.fetch_token_balances(
            "0x2222222222222222222222222222222222222222",
            "robinhood",
        )
        assert len(balances) == 1
        assert seen_urls[-1] == "https://gateway.example/v1/evm/rpc/robinhood?provider=alchemy"
    finally:
        evm_portfolio.get_client = original_get_client
        await client.aclose()
        settings.provider_gateway_url = original_values["provider_gateway_url"]
        settings.provider_gateway_bearer_token = original_values["provider_gateway_bearer_token"]
        os.environ.pop("PROVIDER_GATEWAY_URL", None)
        os.environ.pop("PROVIDER_GATEWAY_BEARER_TOKEN", None)


def main() -> None:
    asyncio.run(_run())
    print("smoke_evm_portfolio_gateway: ok")


if __name__ == "__main__":
    main()
