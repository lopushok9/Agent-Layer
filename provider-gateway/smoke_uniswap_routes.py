"""Smoke coverage for provider-gateway Uniswap Trading API proxy routes."""

from __future__ import annotations

import os

from starlette.testclient import TestClient

import app as gateway_app


def main() -> None:
    original_env = {
        "REQUIRE_BEARER_AUTH": os.environ.get("REQUIRE_BEARER_AUTH"),
        "PROVIDER_GATEWAY_BEARER_TOKEN": os.environ.get("PROVIDER_GATEWAY_BEARER_TOKEN"),
        "UNISWAP_API_KEY": os.environ.get("UNISWAP_API_KEY"),
        "UNISWAP_TRADING_API_BASE_URL": os.environ.get("UNISWAP_TRADING_API_BASE_URL"),
        "UNISWAP_ROUTER_VERSION": os.environ.get("UNISWAP_ROUTER_VERSION"),
        "UNISWAP_ROUTER_VERSION_BY_CHAIN": os.environ.get("UNISWAP_ROUTER_VERSION_BY_CHAIN"),
    }
    original_http_post = gateway_app._http_post

    seen: dict[str, object] = {}

    async def fake_http_post(url: str, *, headers=None, json_body=None):
        seen["post"] = {"url": url, "headers": headers, "json_body": json_body}
        if url.endswith("/quote"):
            return 200, {"routing": "CLASSIC", "quote": {"output": {"amount": "990000"}}}
        if url.endswith("/swap"):
            return 200, {"swap": {"to": "0xrouter", "data": "0xabc", "value": "0x0"}}
        if url.endswith("/order"):
            return 200, {"orderId": "0xorder", "orderStatus": "open"}
        raise AssertionError(f"Unexpected POST request: {url}")

    try:
        os.environ["REQUIRE_BEARER_AUTH"] = "true"
        os.environ["PROVIDER_GATEWAY_BEARER_TOKEN"] = "test-token"
        os.environ["UNISWAP_API_KEY"] = "uniswap-test-key"
        os.environ["UNISWAP_TRADING_API_BASE_URL"] = "https://uniswap.example/v1"
        os.environ["UNISWAP_ROUTER_VERSION"] = "2.0"
        os.environ["UNISWAP_ROUTER_VERSION_BY_CHAIN"] = '{"1":"2.0","8453":"2.0","4663":"2.0"}'

        gateway_app._http_post = fake_http_post

        client = TestClient(gateway_app.app)
        headers = {
            "Authorization": "Bearer test-token",
            "x-agentlayer-chain-id": "4663",
            "x-agentlayer-uniswap-router-version": "2.0",
        }

        # Unauthorized without a token.
        assert client.post("/v1/evm/uniswap/quote", json={"x": 1}).status_code == 401
        assert client.post("/v1/evm/uniswap/swap", json={"x": 1}).status_code == 401

        # Quote: key + router version injected, base URL + path correct, body passed through.
        quote = client.post(
            "/v1/evm/uniswap/quote",
            headers=headers,
            json={"tokenIn": "0xa", "tokenOut": "0xb", "amount": "100000"},
        )
        assert quote.status_code == 200, quote.text
        assert quote.json()["routing"] == "CLASSIC"
        assert seen["post"]["url"] == "https://uniswap.example/v1/quote"
        assert seen["post"]["headers"]["x-api-key"] == "uniswap-test-key"
        assert seen["post"]["headers"]["x-universal-router-version"] == "2.0"
        assert seen["post"]["json_body"]["amount"] == "100000"

        # Native-ETH UniswapX mode is forwarded only as a fixed allow-listed header.
        quote_native = client.post(
            "/v1/evm/uniswap/quote",
            headers={**headers, "x-erc20eth-enabled": "true"},
            json={"tokenIn": "0xa", "tokenOut": "0xb", "amount": "100000"},
        )
        assert quote_native.status_code == 200, quote_native.text
        assert seen["post"]["headers"]["x-erc20eth-enabled"] == "true"

        # The gateway uses its own configured version and rejects a client whose
        # reviewed wallet profile is out of sync; it never forwards a caller's
        # raw x-universal-router-version header.
        mismatch = client.post(
            "/v1/evm/uniswap/quote",
            headers={**headers, "x-agentlayer-uniswap-router-version": "2.1.1"},
            json={"tokenIn": "0xa", "tokenOut": "0xb", "amount": "100000"},
        )
        assert mismatch.status_code == 400, mismatch.text

        # A signed UniswapX order is routed only to the fixed /order upstream path.
        order = client.post(
            "/v1/evm/uniswap/order",
            headers=headers,
            json={"quote": {"output": {"amount": "990000"}}, "routing": "DUTCH_V3", "signature": "0xsig"},
        )
        assert order.status_code == 200, order.text
        assert order.json()["orderId"] == "0xorder"
        assert seen["post"]["url"] == "https://uniswap.example/v1/order"

        limit_order = client.post(
            "/v1/evm/uniswap/order",
            headers=headers,
            json={"quote": {"output": {"amount": "990000"}}, "routing": "LIMIT_ORDER", "signature": "0xsig"},
        )
        assert limit_order.status_code == 200, limit_order.text
        assert seen["post"]["json_body"]["routing"] == "LIMIT_ORDER"

        assert client.post(
            "/v1/evm/uniswap/order", headers=headers, json={"quote": {}}
        ).status_code == 400

        # Swap: routed to /swap, body passed through.
        swap = client.post(
            "/v1/evm/uniswap/swap",
            headers=headers,
            json={"quote": {"output": {"amount": "990000"}}, "signature": "0xsig"},
        )
        assert swap.status_code == 200, swap.text
        assert swap.json()["swap"]["to"] == "0xrouter"
        assert seen["post"]["url"] == "https://uniswap.example/v1/swap"

        # Machine token via query param is also accepted (matches EVM RPC auth).
        quote_q = client.post(
            "/v1/evm/uniswap/quote?token=test-token",
            json={"tokenIn": "0xa", "tokenOut": "0xb", "amount": "1"},
        )
        assert quote_q.status_code == 200, quote_q.text

        # Not configured -> 503.
        os.environ["UNISWAP_API_KEY"] = ""
        not_configured = client.post("/v1/evm/uniswap/quote", headers=headers, json={"x": 1})
        assert not_configured.status_code == 503, not_configured.text

        # Status surfaces uniswap config flag.
        os.environ["UNISWAP_API_KEY"] = "uniswap-test-key"
        status = client.get("/v1/status", headers=headers)
        assert status.json()["uniswap_configured"] is True
    finally:
        gateway_app._http_post = original_http_post
        for key, value in original_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    print("smoke_uniswap_routes: ok")


if __name__ == "__main__":
    main()
