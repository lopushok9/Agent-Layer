"""Smoke coverage for Bags provider gateway helpers."""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agent_wallet import providers  # noqa: E402
from agent_wallet.providers import bags  # noqa: E402


async def main() -> None:
    original_env = {
        "PROVIDER_GATEWAY_URL": os.environ.get("PROVIDER_GATEWAY_URL"),
        "PROVIDER_GATEWAY_BEARER_TOKEN": os.environ.get("PROVIDER_GATEWAY_BEARER_TOKEN"),
    }
    original_get_client = bags.get_client

    seen: list[tuple[str, str, str | None]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append((request.method, str(request.url), request.headers.get("authorization")))
        if request.url.path.endswith("/v1/bags/launch/token-info"):
            body = json.loads(request.content.decode())
            assert body["name"] == "OpenClaw"
            return httpx.Response(
                200,
                json={
                    "success": True,
                    "response": {
                        "tokenMint": "mint-123",
                        "tokenMetadata": "ipfs://metadata.json",
                        "tokenLaunch": {"uri": "ipfs://metadata.json"},
                    },
                },
            )
        if request.url.path.endswith("/v1/bags/launch/fee-share-config"):
            return httpx.Response(
                200,
                json={
                    "success": True,
                    "response": {
                        "needsCreation": True,
                        "feeShareAuthority": "authority",
                        "meteoraConfigKey": "cfg",
                        "transactions": [
                            {
                                "blockhash": {
                                    "blockhash": "blockhash-a",
                                    "lastValidBlockHeight": 123,
                                },
                                "transaction": "fee-share-create-tx",
                            }
                        ],
                        "bundles": [
                            [
                                {
                                    "blockhash": {
                                        "blockhash": "blockhash-b",
                                        "lastValidBlockHeight": 456,
                                    },
                                    "transaction": "fee-share-bundle-tx",
                                }
                            ]
                        ],
                    },
                },
            )
        if request.url.path.endswith("/v1/bags/launch/transaction"):
            return httpx.Response(200, json={"success": True, "response": "base58-launch-tx"})
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))

    try:
        os.environ["PROVIDER_GATEWAY_URL"] = "https://gateway.example"
        os.environ["PROVIDER_GATEWAY_BEARER_TOKEN"] = "gateway-token"
        bags.get_client = lambda: client
        providers.bags.get_client = bags.get_client

        token_info = await bags.create_token_info(
            {
                "name": "OpenClaw",
                "symbol": "CLAW",
                "description": "Launch test",
            }
        )
        assert token_info["tokenMint"] == "mint-123"
        assert token_info["tokenMetadata"] == "ipfs://metadata.json"
        assert token_info["tokenLaunch"]["uri"] == "ipfs://metadata.json"

        config = await bags.create_fee_share_config(
            {
                "claimersArray": ["wallet-a"],
                "basisPointsArray": [10000],
            }
        )
        assert config["needsCreation"] is True
        assert config["meteoraConfigKey"] == "cfg"
        assert config["transactions"][0]["transaction"] == "fee-share-create-tx"
        assert config["bundles"][0][0]["transaction"] == "fee-share-bundle-tx"

        launch_tx = await bags.create_launch_transaction(
            {
                "ipfs": "ipfs://metadata",
                "tokenMint": "mint-123",
                "wallet": "wallet-a",
                "configKey": "cfg",
                "initialBuyLamports": 1000000,
            }
        )
        assert launch_tx == "base58-launch-tx"

        assert all(item[2] == "Bearer gateway-token" for item in seen)
        print("smoke_bags_provider_gateway: ok")
    finally:
        bags.get_client = original_get_client
        providers.bags.get_client = original_get_client
        await client.aclose()
        for key, value in original_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


if __name__ == "__main__":
    asyncio.run(main())
