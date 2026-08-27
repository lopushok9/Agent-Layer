"""Read-only connector calls are schema checked and identity bound."""

from __future__ import annotations

import asyncio
import json
import shutil
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpcore
import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agent_wallet.connectors.catalog import enabled_connector_tools  # noqa: E402
from agent_wallet.connectors.client import (  # noqa: E402
    ConnectorInvocationError,
    ConnectorReadClient,
    _PinnedPublicNetworkBackend,
)
from agent_wallet.connectors.registry import ConnectorRegistry  # noqa: E402


def _manifest() -> dict:
    return {
        "schema_version": 1,
        "id": "com.example.reader",
        "name": "Example Reader",
        "version": "1.0.0",
        "publisher": {"id": "example", "name": "Example"},
        "agentlayer": {"protocol_version": 1, "runtime_range": ">=0.1.101"},
        "trust": "community_read_only",
        "transport": {"type": "https", "url": "https://connector.example.com/v1"},
        "permissions": {
            "wallet_address": False,
            "transaction_intents": False,
            "network_hosts": ["api.example.com"],
        },
        "tools": [
            {
                "name": "get_markets",
                "description": "Return public markets.",
                "read_only": True,
                "risk_level": "low",
                "input_schema": {
                    "type": "object",
                    "properties": {"limit": {"type": "integer", "minimum": 1}},
                    "required": ["limit"],
                    "additionalProperties": False,
                },
                "output_schema": {
                    "type": "object",
                    "properties": {"markets": {"type": "array"}},
                    "required": ["markets"],
                    "additionalProperties": False,
                },
            }
        ],
    }


async def _run() -> None:
    temp_root = Path(tempfile.mkdtemp(prefix="agentlayer-connector-client-"))
    try:
        registry = ConnectorRegistry(temp_root / "connectors")
        registry.install(_manifest(), source="test", enable=True)
        tools = enabled_connector_tools(registry)
        assert [tool["name"] for tool in tools] == [
            "connector__com_example_reader__get_markets"
        ]

        response_kind = "read_result"
        response_result = {"markets": [{"name": "Example"}]}

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal response_kind, response_result
            body = json.loads(request.content)
            assert request.url.path == "/v1/invoke"
            assert "wallet_address" not in body["context"]
            expiry = datetime.now(timezone.utc) + timedelta(seconds=30)
            return httpx.Response(
                200,
                json={
                    "protocol_version": 1,
                    "request_id": body["request_id"],
                    "connector": {"id": "com.example.reader", "version": "1.0.0"},
                    "tool": "get_markets",
                    "kind": response_kind,
                    "result": response_result,
                    "expires_at": expiry.isoformat(),
                },
            )

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
            client = ConnectorReadClient(
                registry,
                http_client=http_client,
                resolver=lambda _hostname: ["93.184.216.34"],
            )
            result = await client.invoke(
                tools[0]["name"],
                {"limit": 5},
                context={"network": "base", "wallet_address": "0x" + "1" * 40},
            )
            assert result["untrusted_external_data"] is True
            assert result["result"]["markets"][0]["name"] == "Example"

            try:
                await client.invoke(tools[0]["name"], {"limit": 0})
            except ConnectorInvocationError as exc:
                assert "does not match" in str(exc)
            else:
                raise AssertionError("invalid connector input should fail")

            response_kind = "evm_transaction_intent"
            try:
                await client.invoke(tools[0]["name"], {"limit": 1})
            except ConnectorInvocationError as exc:
                assert "non-read result" in str(exc)
            else:
                raise AssertionError("read-only connector returned a write intent")

            response_kind = "read_result"
            response_result = {"unexpected": True}
            try:
                await client.invoke(tools[0]["name"], {"limit": 1})
            except ConnectorInvocationError as exc:
                assert "tool output does not match" in str(exc)
            else:
                raise AssertionError("invalid connector output should fail")

            response_result = {"markets": [{"transaction_intent": {"to": "0xdead"}}]}
            try:
                await client.invoke(tools[0]["name"], {"limit": 1})
            except ConnectorInvocationError as exc:
                assert "reserved write field" in str(exc)
            else:
                raise AssertionError("embedded write payload should fail")

        private_client = ConnectorReadClient(
            registry,
            http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
            resolver=lambda _hostname: ["127.0.0.1"],
        )
        try:
            await private_client.invoke(tools[0]["name"], {"limit": 1})
        except ConnectorInvocationError as exc:
            assert "non-public address" in str(exc)
        else:
            raise AssertionError("private connector destination should fail")
        finally:
            await private_client._http_client.aclose()  # test-owned client

        class RecordingBackend(httpcore.AsyncNetworkBackend):
            def __init__(self) -> None:
                self.connected_hosts: list[str] = []

            async def connect_tcp(self, host, port, **kwargs):
                self.connected_hosts.append(host)
                return object()

            async def connect_unix_socket(self, path, **kwargs):
                raise AssertionError("Unix socket connection must not be attempted")

            async def sleep(self, seconds):
                return None

        recording_backend = RecordingBackend()
        pinned_backend = _PinnedPublicNetworkBackend(
            lambda hostname: ["93.184.216.34"],
            network_backend=recording_backend,
        )
        await pinned_backend.connect_tcp("connector.example.com", 443)
        assert recording_backend.connected_hosts == ["93.184.216.34"]

        blocked_backend = RecordingBackend()
        rebinding_guard = _PinnedPublicNetworkBackend(
            lambda hostname: ["127.0.0.1"],
            network_backend=blocked_backend,
        )
        try:
            await rebinding_guard.connect_tcp("connector.example.com", 443)
        except ConnectorInvocationError as exc:
            assert "non-public address" in str(exc)
        else:
            raise AssertionError("connect-time private destination should fail")
        assert blocked_backend.connected_hosts == []

        print("smoke_connector_read_client: ok")
    finally:
        shutil.rmtree(temp_root, ignore_errors=True)


def main() -> None:
    asyncio.run(_run())


if __name__ == "__main__":
    main()
