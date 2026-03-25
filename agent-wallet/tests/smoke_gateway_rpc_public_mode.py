"""Smoke test for provider-gateway RPC mode without bearer auth."""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agent_wallet.providers import solana_rpc  # noqa: E402


async def _run() -> None:
    original_env = {
        "PROVIDER_GATEWAY_BEARER_TOKEN": os.environ.get("PROVIDER_GATEWAY_BEARER_TOKEN"),
    }
    original_get_client = solana_rpc.get_client

    seen_headers: list[str | None] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_headers.append(request.headers.get("authorization"))
        assert request.url == httpx.URL("https://gateway.example/v1/rpc")
        payload = request.read().decode()
        assert '"method":"getLatestBlockhash"' in payload
        return httpx.Response(
            200,
            json={
                "ok": True,
                "provider": "shared",
                "upstream_status": 200,
                "rpc": {"jsonrpc": "2.0", "result": {"value": {"blockhash": "abc"}}},
            },
        )

    client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        base_url="https://gateway.example",
    )
    try:
        os.environ.pop("PROVIDER_GATEWAY_BEARER_TOKEN", None)
        solana_rpc.get_client = lambda: client
        data = await solana_rpc.rpc_call(
            "getLatestBlockhash",
            [{"commitment": "confirmed"}],
            "gateway::shared::mainnet::https://gateway.example/v1/rpc",
        )
        assert data["result"]["value"]["blockhash"] == "abc"
        assert seen_headers == [None]
    finally:
        solana_rpc.get_client = original_get_client
        await client.aclose()
        for key, value in original_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def main() -> None:
    asyncio.run(_run())
    print("smoke_gateway_rpc_public_mode: ok")


if __name__ == "__main__":
    main()
