"""Smoke coverage for provider-gateway Flash Trade read routes."""

from __future__ import annotations

import os

from starlette.testclient import TestClient

import app as gateway_app


def main() -> None:
    original_env = {
        "REQUIRE_BEARER_AUTH": os.environ.get("REQUIRE_BEARER_AUTH"),
        "PROVIDER_GATEWAY_BEARER_TOKEN": os.environ.get("PROVIDER_GATEWAY_BEARER_TOKEN"),
        "FLASH_API_BASE_URL": os.environ.get("FLASH_API_BASE_URL"),
    }
    original_http_get = gateway_app._http_get

    seen: dict[str, object] = {}

    async def fake_http_get(url: str, *, headers=None, params=None):
        seen["get"] = {"url": url, "headers": headers, "params": params}
        if url.endswith("/markets"):
            return 200, {"markets": [{"symbol": "SOL-PERP", "poolName": "Crypto.1"}]}
        if url.endswith("/positions"):
            return 200, {"positions": [{"owner": "wallet-a", "symbol": "SOL-PERP"}]}
        raise AssertionError(f"Unexpected GET request: {url}")

    try:
        os.environ["REQUIRE_BEARER_AUTH"] = "true"
        os.environ["PROVIDER_GATEWAY_BEARER_TOKEN"] = "test-token"
        os.environ["FLASH_API_BASE_URL"] = "https://flash.example/perps"

        gateway_app._http_get = fake_http_get

        client = TestClient(gateway_app.app)
        headers = {"Authorization": "Bearer test-token"}

        markets = client.get("/v1/flash/perps/markets", headers=headers)
        assert markets.status_code == 200
        assert markets.json()["markets"][0]["symbol"] == "SOL-PERP"
        assert seen["get"]["url"] == "https://flash.example/perps/markets"
        assert seen["get"]["params"] is None

        filtered_markets = client.get(
            "/v1/flash/perps/markets",
            headers=headers,
            params={"pool_name": "Crypto.1"},
        )
        assert filtered_markets.status_code == 200
        assert seen["get"]["params"] == {"pool_name": "Crypto.1"}

        invalid_positions = client.get("/v1/flash/perps/positions", headers=headers)
        assert invalid_positions.status_code == 400

        positions = client.get(
            "/v1/flash/perps/positions",
            headers=headers,
            params={"owner": "wallet-a", "pool_name": "Crypto.1"},
        )
        assert positions.status_code == 200
        assert positions.json()["positions"][0]["owner"] == "wallet-a"
        assert seen["get"]["url"] == "https://flash.example/perps/positions"
        assert seen["get"]["params"] == {
            "owner": "wallet-a",
            "pool_name": "Crypto.1",
        }

        print("smoke_flash_routes: ok")
    finally:
        gateway_app._http_get = original_http_get
        for key, value in original_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


if __name__ == "__main__":
    main()
