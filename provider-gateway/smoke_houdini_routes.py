"""Smoke coverage for provider-gateway Houdini routes."""

from __future__ import annotations

import os

from starlette.testclient import TestClient

import app as gateway_app


def main() -> None:
    original_env = {
        "REQUIRE_BEARER_AUTH": os.environ.get("REQUIRE_BEARER_AUTH"),
        "PROVIDER_GATEWAY_BEARER_TOKEN": os.environ.get("PROVIDER_GATEWAY_BEARER_TOKEN"),
        "HOUDINI_API_KEY": os.environ.get("HOUDINI_API_KEY"),
        "HOUDINI_API_SECRET": os.environ.get("HOUDINI_API_SECRET"),
        "HOUDINI_API_BASE_URL": os.environ.get("HOUDINI_API_BASE_URL"),
        "HOUDINI_USER_AGENT": os.environ.get("HOUDINI_USER_AGENT"),
        "HOUDINI_USER_TIMEZONE": os.environ.get("HOUDINI_USER_TIMEZONE"),
    }
    original_http_get = gateway_app._http_get
    original_http_post = gateway_app._http_post

    seen: dict[str, object] = {}

    async def fake_http_get(url: str, *, headers=None, params=None):
        seen["get"] = {"url": url, "headers": headers, "params": params}
        if url.endswith("/tokens"):
            return 200, {"tokens": [{"id": "sol-token-id", "symbol": "SOL"}], "totalPages": 1}
        if url.endswith("/quotes"):
            return 200, {
                "quotes": [
                    {
                        "quoteId": "private-quote-1",
                        "type": "private",
                        "amountOut": 0.0985,
                        "duration": 28,
                    }
                ]
            }
        if url.endswith("/tx"):
            return 200, {
                "multiId": "multi-1",
                "transactions": [{"houdiniIds": ["houdini-1"], "txData": {"data": "ZmFrZS10eA=="}}],
            }
        if "/exchanges/multi/" in url:
            return 200, {"multiId": "multi-1", "orders": [{"houdiniId": "houdini-1", "statusLabel": "WAITING"}]}
        raise AssertionError(f"Unexpected GET request: {url}")

    async def fake_http_post(url: str, *, headers=None, json_body=None):
        seen["post"] = {"url": url, "headers": headers, "json_body": json_body}
        if url.endswith("/exchanges/multi"):
            return 200, {
                "multiId": "multi-1",
                "orders": [{"order": {"houdiniId": "houdini-1", "depositAddress": "deposit-1"}}],
            }
        raise AssertionError(f"Unexpected POST request: {url}")

    try:
        os.environ["REQUIRE_BEARER_AUTH"] = "true"
        os.environ["PROVIDER_GATEWAY_BEARER_TOKEN"] = "test-token"
        os.environ["HOUDINI_API_KEY"] = "houdini-key"
        os.environ["HOUDINI_API_SECRET"] = "houdini-secret"
        os.environ["HOUDINI_API_BASE_URL"] = "https://houdini.example/v2"
        os.environ["HOUDINI_USER_AGENT"] = "GatewaySmoke/1.0"
        os.environ["HOUDINI_USER_TIMEZONE"] = "UTC"

        gateway_app._http_get = fake_http_get
        gateway_app._http_post = fake_http_post

        client = TestClient(gateway_app.app)
        headers = {
            "Authorization": "Bearer test-token",
            "x-forwarded-for": "203.0.113.25, 10.0.0.1",
            "x-user-agent": "AgentLayerSmoke/1.0",
            "x-user-timezone": "Europe/Moscow",
        }

        tokens = client.get("/v1/houdini/tokens", headers=headers, params={"chain": "solana", "hasCex": "true"})
        assert tokens.status_code == 200
        assert tokens.json()["tokens"][0]["symbol"] == "SOL"
        assert seen["get"]["url"] == "https://houdini.example/v2/tokens"
        assert seen["get"]["params"] == {"chain": "solana", "hasCex": "true"}
        assert seen["get"]["headers"]["Authorization"] == "houdini-key:houdini-secret"
        assert seen["get"]["headers"]["x-user-ip"] == "203.0.113.25"
        assert seen["get"]["headers"]["x-user-agent"] == "AgentLayerSmoke/1.0"
        assert seen["get"]["headers"]["x-user-timezone"] == "Europe/Moscow"

        quotes = client.get(
            "/v1/houdini/quotes/private",
            headers=headers,
            params={"from": "sol-token-id", "to": "sol-token-id", "amount": "0.1"},
        )
        assert quotes.status_code == 200
        assert quotes.json()["quotes"][0]["quoteId"] == "private-quote-1"
        assert seen["get"]["url"] == "https://houdini.example/v2/quotes"
        assert seen["get"]["params"] == {
            "from": "sol-token-id",
            "to": "sol-token-id",
            "amount": "0.1",
            "types": "private",
        }

        create = client.post(
            "/v1/houdini/exchanges/multi",
            headers=headers,
            json={"orders": [{"from": "sol-token-id", "to": "sol-token-id", "amount": 0.1}]},
        )
        assert create.status_code == 200
        assert create.json()["multiId"] == "multi-1"
        assert seen["post"]["url"] == "https://houdini.example/v2/exchanges/multi"

        status = client.get("/v1/houdini/exchanges/multi/multi-1", headers=headers)
        assert status.status_code == 200
        assert status.json()["orders"][0]["statusLabel"] == "WAITING"

        tx = client.get(
            "/v1/houdini/exchanges/multi/multi-1/tx",
            headers=headers,
            params={"sender": "FakeSender1111111111111111111111111111111111"},
        )
        assert tx.status_code == 200
        assert tx.json()["transactions"][0]["houdiniIds"] == ["houdini-1"]
        assert seen["get"]["url"] == "https://houdini.example/v2/exchanges/multi/multi-1/tx"
        assert seen["get"]["params"] == {"sender": "FakeSender1111111111111111111111111111111111"}

        print("smoke_houdini_routes: ok")
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
