"""Smoke coverage for provider-gateway Bags launch and fee routes."""

from __future__ import annotations

import os

from starlette.testclient import TestClient

import app as gateway_app


def main() -> None:
    original_env = {
        "REQUIRE_BEARER_AUTH": os.environ.get("REQUIRE_BEARER_AUTH"),
        "PROVIDER_GATEWAY_BEARER_TOKEN": os.environ.get("PROVIDER_GATEWAY_BEARER_TOKEN"),
        "BAGS_API_KEY": os.environ.get("BAGS_API_KEY"),
        "BAGS_API_BASE_URL": os.environ.get("BAGS_API_BASE_URL"),
    }
    original_http_get = gateway_app._http_get
    original_http_post = gateway_app._http_post
    original_http_post_form = gateway_app._http_post_form

    seen: dict[str, object] = {}

    async def fake_http_get(url: str, *, headers=None, params=None):
        seen["get"] = {"url": url, "headers": headers, "params": params}
        if url.endswith("/token-launch/lifetime-fees"):
            return 200, {"success": True, "response": {"totalFees": "42"}}
        if url.endswith("/token-launch/claim-stats"):
            return 200, {"success": True, "response": [{"wallet": "claimer"}]}
        if url.endswith("/fee-share/token/claim-events"):
            return 200, {"success": True, "response": {"events": [{"wallet": "claimer"}]}}
        return 200, {"success": True, "response": {"ok": True}}

    async def fake_http_post(url: str, *, headers=None, json_body=None):
        seen["post"] = {"url": url, "headers": headers, "json_body": json_body}
        if url.endswith("/fee-share/config"):
            return 200, {
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
            }
        if url.endswith("/token-launch/create-launch-transaction"):
            return 200, {"success": True, "response": "base58-launch-tx"}
        return 200, {"success": True, "response": {"ok": True}}

    async def fake_http_post_form(url: str, *, headers=None, data_body=None, files=None):
        seen["post_form"] = {
            "url": url,
            "headers": headers,
            "data_body": data_body,
            "files": files,
        }
        return 200, {
            "success": True,
            "response": {
                "tokenMint": "mint-123",
                "tokenMetadata": "ipfs://metadata.json",
                "tokenLaunch": {
                    "name": data_body["name"],
                    "symbol": data_body["symbol"],
                    "description": data_body["description"],
                    "uri": "ipfs://metadata.json",
                },
            },
        }

    try:
        os.environ["REQUIRE_BEARER_AUTH"] = "true"
        os.environ["PROVIDER_GATEWAY_BEARER_TOKEN"] = "test-token"
        os.environ["BAGS_API_KEY"] = "bags-test-key"
        os.environ["BAGS_API_BASE_URL"] = "https://bags.example/api/v1"

        gateway_app._http_get = fake_http_get
        gateway_app._http_post = fake_http_post
        gateway_app._http_post_form = fake_http_post_form

        client = TestClient(gateway_app.app)
        headers = {"Authorization": "Bearer test-token"}

        token_info = client.post(
            "/v1/bags/launch/token-info",
            headers=headers,
            json={
                "name": "OpenClaw",
                "symbol": "CLAW",
                "description": "Launch test",
                "imageUrl": "https://example.com/claw.png",
                "website": "https://openclaw.ai",
            },
        )
        assert token_info.status_code == 200
        assert token_info.json()["response"]["tokenMint"] == "mint-123"
        assert token_info.json()["response"]["tokenMetadata"] == "ipfs://metadata.json"
        assert token_info.json()["response"]["tokenLaunch"]["uri"] == "ipfs://metadata.json"
        assert seen["post_form"]["url"] == "https://bags.example/api/v1/token-launch/create-token-info"

        invalid_fee_share = client.post(
            "/v1/bags/launch/fee-share-config",
            headers=headers,
            json={
                "payer": "wallet-a",
                "baseMint": "mint-123",
                "claimersArray": ["wallet-a", "wallet-b"],
                "basisPointsArray": [4000, 4000],
            },
        )
        assert invalid_fee_share.status_code == 400

        fee_share = client.post(
            "/v1/bags/launch/fee-share-config",
            headers=headers,
            json={
                "payer": "wallet-a",
                "baseMint": "mint-123",
                "claimersArray": ["wallet-a", "wallet-b"],
                "basisPointsArray": [7000, 3000],
                "bagsConfigType": 2,
            },
        )
        assert fee_share.status_code == 200
        fee_share_response = fee_share.json()["response"]
        assert fee_share_response["needsCreation"] is True
        assert fee_share_response["meteoraConfigKey"] == "cfg"
        assert fee_share_response["transactions"][0]["transaction"] == "fee-share-create-tx"
        assert fee_share_response["bundles"][0][0]["transaction"] == "fee-share-bundle-tx"

        launch_tx = client.post(
            "/v1/bags/launch/transaction",
            headers=headers,
            json={
                "ipfs": "ipfs://metadata",
                "tokenMint": "mint-123",
                "wallet": "wallet-a",
                "configKey": "cfg",
                "initialBuyLamports": 10000000,
            },
        )
        assert launch_tx.status_code == 200
        assert launch_tx.json()["response"] == "base58-launch-tx"

        lifetime = client.get(
            "/v1/bags/fees/lifetime",
            headers=headers,
            params={"tokenMint": "mint-123"},
        )
        assert lifetime.status_code == 200
        assert lifetime.json()["response"]["totalFees"] == "42"

        claim_stats = client.get(
            "/v1/bags/fees/claim-stats",
            headers=headers,
            params={"tokenMint": "mint-123"},
        )
        assert claim_stats.status_code == 200
        assert claim_stats.json()["response"][0]["wallet"] == "claimer"

        claim_events = client.get(
            "/v1/bags/fees/claim-events",
            headers=headers,
            params={"tokenMint": "mint-123", "mode": "time", "from": "10", "to": "20"},
        )
        assert claim_events.status_code == 200
        assert claim_events.json()["response"]["events"][0]["wallet"] == "claimer"
        assert seen["get"]["params"] == {"tokenMint": "mint-123", "mode": "time", "from": "10", "to": "20"}

        print("smoke_bags_routes: ok")
    finally:
        gateway_app._http_get = original_http_get
        gateway_app._http_post = original_http_post
        gateway_app._http_post_form = original_http_post_form
        for key, value in original_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


if __name__ == "__main__":
    main()
