"""Smoke coverage for provider-gateway EVM RPC routes."""

from __future__ import annotations

import os

from starlette.testclient import TestClient

import app as gateway_app


def main() -> None:
    original_env = {
        "REQUIRE_BEARER_AUTH": os.environ.get("REQUIRE_BEARER_AUTH"),
        "PROVIDER_GATEWAY_BEARER_TOKEN": os.environ.get("PROVIDER_GATEWAY_BEARER_TOKEN"),
        "ALCHEMY_API_KEY": os.environ.get("ALCHEMY_API_KEY"),
        "ALCHEMY_ETHEREUM_RPC_URL": os.environ.get("ALCHEMY_ETHEREUM_RPC_URL"),
        "ALCHEMY_BASE_RPC_URL": os.environ.get("ALCHEMY_BASE_RPC_URL"),
        "SHARED_EVM_ETHEREUM_RPC_URL": os.environ.get("SHARED_EVM_ETHEREUM_RPC_URL"),
        "SHARED_EVM_BASE_RPC_URL": os.environ.get("SHARED_EVM_BASE_RPC_URL"),
    }
    original_http_post = gateway_app._http_post

    seen: dict[str, object] = {}

    async def fake_http_post(url: str, *, headers=None, json_body=None):
        seen["post"] = {"url": url, "headers": headers, "json_body": json_body}
        return 200, {"jsonrpc": "2.0", "id": json_body.get("id"), "result": "0x1"}

    try:
        os.environ["REQUIRE_BEARER_AUTH"] = "true"
        os.environ["PROVIDER_GATEWAY_BEARER_TOKEN"] = "test-token"
        os.environ["ALCHEMY_API_KEY"] = "alchemy-key"
        os.environ.pop("ALCHEMY_ETHEREUM_RPC_URL", None)
        os.environ.pop("ALCHEMY_BASE_RPC_URL", None)
        os.environ.pop("SHARED_EVM_ETHEREUM_RPC_URL", None)
        os.environ.pop("SHARED_EVM_BASE_RPC_URL", None)

        gateway_app._http_post = fake_http_post

        client = TestClient(gateway_app.app)

        unauthorized = client.post(
            "/v1/evm/rpc/ethereum",
            json={"jsonrpc": "2.0", "id": 1, "method": "eth_chainId", "params": []},
        )
        assert unauthorized.status_code == 401

        allowed = client.post(
            "/v1/evm/rpc/ethereum?provider=alchemy&token=test-token",
            json={"jsonrpc": "2.0", "id": 7, "method": "eth_chainId", "params": []},
        )
        assert allowed.status_code == 200
        assert allowed.json()["result"] == "0x1"
        assert seen["post"]["url"] == "https://eth-mainnet.g.alchemy.com/v2/alchemy-key"
        assert seen["post"]["json_body"] == {
            "jsonrpc": "2.0",
            "id": 7,
            "method": "eth_chainId",
            "params": [],
        }

        base_allowed = client.post(
            "/v1/evm/rpc/base?provider=alchemy&token=test-token",
            json={"jsonrpc": "2.0", "id": 9, "method": "eth_blockNumber", "params": []},
        )
        assert base_allowed.status_code == 200
        assert seen["post"]["url"] == "https://base-mainnet.g.alchemy.com/v2/alchemy-key"

        forbidden_method = client.post(
            "/v1/evm/rpc/ethereum?provider=alchemy&token=test-token",
            json={"jsonrpc": "2.0", "id": 3, "method": "debug_traceTransaction", "params": []},
        )
        assert forbidden_method.status_code == 403

        unsupported_network = client.post(
            "/v1/evm/rpc/sepolia?provider=alchemy&token=test-token",
            json={"jsonrpc": "2.0", "id": 4, "method": "eth_chainId", "params": []},
        )
        assert unsupported_network.status_code == 403

        print("smoke_evm_rpc_routes: ok")
    finally:
        gateway_app._http_post = original_http_post
        for key, value in original_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


if __name__ == "__main__":
    main()
