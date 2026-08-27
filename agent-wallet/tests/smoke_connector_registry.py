"""Connector registry persists immutable manifests outside wallet releases."""

from __future__ import annotations

import copy
import json
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agent_wallet.connectors.registry import ConnectorRegistry, ConnectorRegistryError  # noqa: E402


def _manifest(version: str = "1.0.0") -> dict:
    return {
        "schema_version": 1,
        "id": "com.example.markets",
        "name": "Example Markets",
        "version": version,
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
                "description": "Return markets.",
                "read_only": True,
                "risk_level": "low",
                "input_schema": {"type": "object"},
                "output_schema": {"type": "object"},
            }
        ],
    }


def _expect_error(callback, message: str) -> None:
    try:
        callback()
    except ConnectorRegistryError as exc:
        assert message in str(exc), exc
    else:
        raise AssertionError(f"expected registry error containing: {message}")


def main() -> None:
    temp_root = Path(tempfile.mkdtemp(prefix="agentlayer-connector-registry-"))
    try:
        registry = ConnectorRegistry(temp_root / "connectors")
        assert registry.list() == []

        installed = registry.install(_manifest(), source="test-fixture")
        assert installed["enabled"] is False
        assert installed["installed_versions"] == ["1.0.0"]

        enabled = registry.enable("com.example.markets")
        assert enabled["enabled"] is True
        assert enabled["enabled_version"] == "1.0.0"
        assert enabled["restart_required"] is True
        loaded = registry.load_manifest("com.example.markets")
        assert loaded["version"] == "1.0.0"

        registry.install(_manifest("1.1.0"), source="test-fixture")
        upgraded = registry.enable("com.example.markets", version="1.1.0")
        assert upgraded["installed_versions"] == ["1.0.0", "1.1.0"]
        assert upgraded["enabled_version"] == "1.1.0"

        mutated = copy.deepcopy(_manifest("1.1.0"))
        mutated["transport"]["url"] = "https://changed.example.com/v1"
        _expect_error(
            lambda: registry.install(mutated, source="mutated"),
            "versions are immutable",
        )
        _expect_error(
            lambda: registry.remove("com.example.markets", version="1.1.0"),
            "Disable",
        )

        registry.disable("com.example.markets")
        removed = registry.remove("com.example.markets", version="1.1.0")
        assert removed["removed"] is True
        assert registry.list()[0]["installed_versions"] == ["1.0.0"]

        registry_path = registry.registry_path
        registry_path.write_text("not-json", encoding="utf-8")
        _expect_error(registry.read, "unreadable")

        registry_path.write_text(
            json.dumps({"schema_version": 99, "connectors": {}}), encoding="utf-8"
        )
        _expect_error(registry.read, "schema is invalid")

        registry_path.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "connectors": {
                        "com.example.escape": {
                            "enabled_version": "1.0.0",
                            "installed_versions": {
                                "1.0.0": {
                                    "manifest_path": "../../outside.json",
                                    "manifest_digest": "sha256:" + "0" * 64,
                                }
                            },
                        }
                    },
                }
            ),
            encoding="utf-8",
        )
        _expect_error(
            lambda: registry.load_manifest("com.example.escape"),
            "escapes the registry",
        )

        print("smoke_connector_registry: ok")
    finally:
        shutil.rmtree(temp_root, ignore_errors=True)


if __name__ == "__main__":
    main()
