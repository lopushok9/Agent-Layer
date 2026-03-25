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
        if request.url.path.endswith("/v1/bags/claim/positions"):
            assert request.url.params["wallet"] == "wallet-a"
            return httpx.Response(
                200,
                json={"success": True, "response": {"positions": [{"tokenMint": "mint-123"}]}},
            )
        if request.url.path.endswith("/v1/bags/claim/transactions"):
            return httpx.Response(
                200,
                json={
                    "success": True,
                    "response": [
                        {
                            "tx": "claim-tx",
                            "blockhash": {
                                "blockhash": "blockhash-claim",
                                "lastValidBlockHeight": 789,
                            },
                        }
                    ],
                },
            )
        if request.url.path.endswith("/v1/bags/fees/lifetime"):
            return httpx.Response(200, json={"success": True, "response": {"totalFees": "42"}})
        if request.url.path.endswith("/v1/bags/fees/claim-stats"):
            return httpx.Response(200, json={"success": True, "response": [{"wallet": "wallet-a"}]})
        if request.url.path.endswith("/v1/bags/fees/claim-events"):
            assert request.url.params["mode"] == "time"
            return httpx.Response(
                200,
                json={"success": True, "response": {"events": [{"wallet": "wallet-a"}]}},
            )
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

        positions = await bags.fetch_claimable_positions("wallet-a")
        assert positions["positions"][0]["tokenMint"] == "mint-123"

        claim_txs = await bags.build_claim_transactions(
            {"feeClaimer": "wallet-a", "tokenMint": "mint-123"}
        )
        assert claim_txs[0]["tx"] == "claim-tx"

        lifetime = await bags.fetch_lifetime_fees("mint-123")
        assert lifetime["totalFees"] == "42"

        claim_stats = await bags.fetch_claim_stats("mint-123")
        assert claim_stats[0]["wallet"] == "wallet-a"

        claim_events = await bags.fetch_claim_events(
            token_mint="mint-123",
            mode="time",
            from_ts=10,
            to_ts=20,
        )
        assert claim_events["events"][0]["wallet"] == "wallet-a"

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
