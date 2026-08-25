"""Enabled read connectors are exposed and invoked through the wallet adapter."""

from __future__ import annotations

import asyncio
import os
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agent_wallet.connectors.registry import ConnectorRegistry  # noqa: E402
from agent_wallet.openclaw_adapter import OpenClawWalletAdapter  # noqa: E402
from agent_wallet.wallet_layer.base import AgentWalletBackend, WalletCapabilities  # noqa: E402


class FakeBackend(AgentWalletBackend):
    name = "fake"
    network = "mainnet"

    async def get_address(self) -> str:
        return "Fake11111111111111111111111111111111111111111"

    async def get_balance(self, address: str | None = None) -> dict[str, Any]:
        return {"address": address}

    def get_capabilities(self) -> WalletCapabilities:
        return WalletCapabilities(
            backend=self.name,
            chain="solana",
            custody_model="local",
            sign_only=False,
            has_signer=True,
        )


class FakeConnectorClient:
    def __init__(self) -> None:
        self.context: dict[str, Any] | None = None

    async def invoke(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        *,
        context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        self.context = context
        return {
            "connector_id": "com.example.markets",
            "connector_version": "1.0.0",
            "tool": "get_markets",
            "untrusted_external_data": True,
            "result": {"markets": []},
            "expires_at": "2099-01-01T00:00:00Z",
        }


async def run() -> None:
    temp_home = Path(tempfile.mkdtemp(prefix="agentlayer-connector-adapter-"))
    previous_home = os.environ.get("OPENCLAW_HOME")
    os.environ["OPENCLAW_HOME"] = str(temp_home)
    try:
        manifest = {
            "schema_version": 1,
            "id": "com.example.markets",
            "name": "Markets",
            "version": "1.0.0",
            "publisher": {"id": "example", "name": "Example"},
            "agentlayer": {"protocol_version": 1, "runtime_range": ">=0.1.101"},
            "trust": "community_read_only",
            "transport": {"type": "https", "url": "https://connector.example.com/v1"},
            "permissions": {
                "wallet_address": False,
                "transaction_intents": False,
                "network_hosts": ["connector.example.com"],
            },
            "tools": [
                {
                    "name": "get_markets",
                    "description": "Read protocol markets.",
                    "read_only": True,
                    "risk_level": "low",
                    "input_schema": {"type": "object", "additionalProperties": False},
                    "output_schema": {"type": "object"},
                }
            ],
        }
        ConnectorRegistry().install(manifest, source="test", enable=True)
        client = FakeConnectorClient()
        adapter = OpenClawWalletAdapter(FakeBackend(), connector_read_client=client)

        connector_name = "connector__com_example_markets__get_markets"
        specs = {spec.name: spec for spec in adapter.list_tools()}
        assert connector_name in specs
        assert specs[connector_name].read_only is True
        assert "get_wallet_balance" in specs

        result = await adapter.invoke(connector_name, {})
        assert result.ok is True
        assert result.data and result.data["untrusted_external_data"] is True
        assert client.context == {
            "chain": "solana",
            "network": "mainnet",
            "chain_id": None,
            "wallet_address": "Fake11111111111111111111111111111111111111111",
        }
    finally:
        if previous_home is None:
            os.environ.pop("OPENCLAW_HOME", None)
        else:
            os.environ["OPENCLAW_HOME"] = previous_home
        shutil.rmtree(temp_home, ignore_errors=True)


if __name__ == "__main__":
    asyncio.run(run())
    print("smoke_connector_openclaw_adapter: ok")
