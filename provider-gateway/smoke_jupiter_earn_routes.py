"""Smoke coverage for provider-gateway Jupiter Earn routes."""

from __future__ import annotations

import os

from starlette.testclient import TestClient

import app as gateway_app


def main() -> None:
    original_env = {
        "REQUIRE_BEARER_AUTH": os.environ.get("REQUIRE_BEARER_AUTH"),
        "PROVIDER_GATEWAY_BEARER_TOKEN": os.environ.get("PROVIDER_GATEWAY_BEARER_TOKEN"),
        "JUPITER_API_KEY": os.environ.get("JUPITER_API_KEY"),
        "JUPITER_LEND_API_BASE_URL": os.environ.get("JUPITER_LEND_API_BASE_URL"),
    }
    original_http_get = gateway_app._http_get
    original_http_post = gateway_app._http_post

    seen: dict[str, object] = {}

    async def fake_http_get(url: str, *, headers=None, params=None):
        seen["get"] = {"url": url, "headers": headers, "params": params}
        if url.endswith("/earn/tokens"):
            return 200, {"tokens": [{"asset": "So111", "symbol": "SOL"}]}
        if url.endswith("/earn/positions"):
            return 200, {"positions": [{"user": "wallet-a", "address": "position-a"}]}
        if url.endswith("/earn/earnings"):
            return 200, {"earnings": [{"user": "wallet-a", "amountUsd": 1.23}]}
        raise AssertionError(f"Unexpected GET request: {url}")

    async def fake_http_post(url: str, *, headers=None, json_body=None):
        seen["post"] = {"url": url, "headers": headers, "json_body": json_body}
        if url.endswith("/earn/deposit"):
            return 200, {"transaction": "deposit-tx", "slot": 123}
        if url.endswith("/earn/withdraw"):
            return 200, {"transaction": "withdraw-tx", "slot": 456}
        raise AssertionError(f"Unexpected POST request: {url}")

    try:
        os.environ["REQUIRE_BEARER_AUTH"] = "true"
        os.environ["PROVIDER_GATEWAY_BEARER_TOKEN"] = "test-token"
        os.environ["JUPITER_API_KEY"] = "jupiter-test-key"
        os.environ["JUPITER_LEND_API_BASE_URL"] = "https://jupiter.example/lend/v1"

        gateway_app._http_get = fake_http_get
        gateway_app._http_post = fake_http_post

        client = TestClient(gateway_app.app)
        headers = {"Authorization": "Bearer test-token"}

        tokens = client.get("/v1/jupiter/earn/tokens", headers=headers)
        assert tokens.status_code == 200
        assert tokens.json()["tokens"][0]["symbol"] == "SOL"
        assert seen["get"]["url"] == "https://jupiter.example/lend/v1/earn/tokens"
        assert seen["get"]["headers"] == {"x-api-key": "jupiter-test-key"}

        invalid_positions = client.get("/v1/jupiter/earn/positions", headers=headers)
        assert invalid_positions.status_code == 400

        positions = client.get(
            "/v1/jupiter/earn/positions",
            headers=headers,
            params={"users": "wallet-a,wallet-b"},
        )
        assert positions.status_code == 200
        assert positions.json()["positions"][0]["address"] == "position-a"
        assert seen["get"]["params"] == {"users": "wallet-a,wallet-b"}

        earnings = client.get(
            "/v1/jupiter/earn/earnings",
            headers=headers,
            params={"user": "wallet-a", "positions": "position-a,position-b"},
        )
        assert earnings.status_code == 200
        assert earnings.json()["earnings"][0]["amountUsd"] == 1.23
        assert seen["get"]["params"] == {
            "user": "wallet-a",
            "positions": "position-a,position-b",
        }

        deposit = client.post(
            "/v1/jupiter/earn/deposit",
            headers=headers,
            json={"asset": "So111", "signer": "wallet-a", "amount": "1000"},
        )
        assert deposit.status_code == 200
        assert deposit.json()["transaction"] == "deposit-tx"
        assert seen["post"]["url"] == "https://jupiter.example/lend/v1/earn/deposit"
        assert seen["post"]["json_body"] == {
            "asset": "So111",
            "signer": "wallet-a",
            "amount": "1000",
        }

        withdraw = client.post(
            "/v1/jupiter/earn/withdraw",
            headers=headers,
            json={"asset": "So111", "signer": "wallet-a", "amount": "500"},
        )
        assert withdraw.status_code == 200
        assert withdraw.json()["transaction"] == "withdraw-tx"
        assert seen["post"]["url"] == "https://jupiter.example/lend/v1/earn/withdraw"
        assert seen["post"]["json_body"] == {
            "asset": "So111",
            "signer": "wallet-a",
            "amount": "500",
        }

        print("smoke_jupiter_earn_routes: ok")
    finally:
        gateway_app._http_get = original_http_get
        gateway_app._http_post = original_http_post
        for key, value in original_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


if __name__ == "__main__":
    main()
