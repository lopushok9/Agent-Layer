"""Connector manifests enforce trust and namespace invariants."""

from __future__ import annotations

import copy
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agent_wallet.connectors.manifest import (  # noqa: E402
    ConnectorManifestError,
    connector_tool_name,
    validate_connector_manifest,
)


def _manifest(*, trust: str = "community_read_only") -> dict:
    is_write = trust == "verified_write"
    payload = {
        "schema_version": 1,
        "id": "com.example.markets",
        "name": "Example Markets",
        "version": "1.0.0",
        "publisher": {"id": "example", "name": "Example"},
        "agentlayer": {"protocol_version": 1, "runtime_range": ">=0.1.101"},
        "trust": trust,
        "transport": {"type": "https", "url": "https://connector.example.com/v1"},
        "permissions": {
            "wallet_address": True,
            "transaction_intents": is_write,
            "network_hosts": ["api.example.com"],
        },
        "tools": [
            {
                "name": "get_markets" if not is_write else "supply",
                "description": "Return markets." if not is_write else "Build a supply intent.",
                "read_only": not is_write,
                "risk_level": "low" if not is_write else "high",
                "input_schema": {"type": "object"},
                "output_schema": {"type": "object"},
            }
        ],
    }
    if is_write:
        payload["artifact_digest"] = "sha256:" + "a" * 64
    return payload


def _expect_invalid(payload: dict, message: str) -> None:
    try:
        validate_connector_manifest(payload)
    except ConnectorManifestError as exc:
        assert message in str(exc), exc
    else:
        raise AssertionError(f"manifest should have failed: {message}")


def main() -> None:
    original = _manifest()
    validated = validate_connector_manifest(original)
    assert validated == original
    assert validated is not original
    assert connector_tool_name("com.example.markets", "get_markets") == (
        "connector__com_example_markets__get_markets"
    )

    write = validate_connector_manifest(_manifest(trust="verified_write"))
    assert write["artifact_digest"].startswith("sha256:")

    bad = copy.deepcopy(original)
    bad["permissions"]["transaction_intents"] = True
    _expect_invalid(bad, "cannot request transaction intents")

    bad = copy.deepcopy(original)
    bad["tools"][0]["read_only"] = False
    _expect_invalid(bad, "only read-only tools")

    bad = _manifest(trust="verified_write")
    bad.pop("artifact_digest")
    _expect_invalid(bad, "require artifact_digest")

    bad = copy.deepcopy(original)
    bad["transport"]["url"] = "http://connector.example.com/v1"
    _expect_invalid(bad, "must be an HTTPS URL")

    bad = copy.deepcopy(original)
    bad["transport"]["timeout_ms"] = 60000
    _expect_invalid(bad, "timeout_ms")

    bad = copy.deepcopy(original)
    bad["permissions"]["network_hosts"] = ["https://api.example.com"]
    _expect_invalid(bad, "must be a hostname")

    bad = copy.deepcopy(original)
    bad["tools"].append(copy.deepcopy(bad["tools"][0]))
    _expect_invalid(bad, "Duplicate connector tool name")

    print("smoke_connector_manifest: ok")


if __name__ == "__main__":
    main()
