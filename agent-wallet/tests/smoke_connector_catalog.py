"""Only enabled read tools enter the initial connector host catalog."""

from __future__ import annotations

import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agent_wallet.connectors.catalog import enabled_connector_tools  # noqa: E402
from agent_wallet.connectors.registry import ConnectorRegistry  # noqa: E402


def main() -> None:
    temp_root = Path(tempfile.mkdtemp(prefix="agentlayer-connector-catalog-"))
    try:
        manifest = {
            "schema_version": 1,
            "id": "com.example.mixed",
            "name": "Mixed Connector",
            "version": "1.0.0",
            "artifact_digest": "sha256:" + "a" * 64,
            "publisher": {"id": "example", "name": "Example"},
            "agentlayer": {"protocol_version": 1, "runtime_range": ">=0.1.101"},
            "trust": "verified_write",
            "transport": {"type": "https", "url": "https://connector.example.com/v1"},
            "permissions": {
                "wallet_address": True,
                "transaction_intents": True,
                "network_hosts": ["api.example.com"],
            },
            "tools": [
                {
                    "name": "get_markets",
                    "description": "Read markets.",
                    "read_only": True,
                    "risk_level": "low",
                    "input_schema": {"type": "object"},
                    "output_schema": {"type": "object"},
                },
                {
                    "name": "supply",
                    "description": "Build a supply intent.",
                    "read_only": False,
                    "risk_level": "high",
                    "input_schema": {"type": "object"},
                    "output_schema": {"type": "object"},
                },
            ],
        }
        registry = ConnectorRegistry(temp_root / "connectors")
        registry.install(manifest, source="test", enable=True)

        safe_tools = enabled_connector_tools(registry)
        assert [tool["connector_tool"] for tool in safe_tools] == ["get_markets"]
        all_tools = enabled_connector_tools(registry, include_write=True)
        assert [tool["connector_tool"] for tool in all_tools] == ["get_markets", "supply"]

        registry.disable("com.example.mixed")
        assert enabled_connector_tools(registry) == []

        print("smoke_connector_catalog: ok")
    finally:
        shutil.rmtree(temp_root, ignore_errors=True)


if __name__ == "__main__":
    main()

