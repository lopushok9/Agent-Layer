"""Codex discovers enabled connectors through the authoritative wallet adapter."""

from __future__ import annotations

import os
import runpy
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agent_wallet.connectors.registry import ConnectorRegistry  # noqa: E402


def main() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    temp_home = Path(tempfile.mkdtemp(prefix="agentlayer-codex-connector-"))
    previous_home = os.environ.get("OPENCLAW_HOME")
    previous_package_root = os.environ.get("AGENT_WALLET_PACKAGE_ROOT")
    os.environ["OPENCLAW_HOME"] = str(temp_home)
    os.environ["AGENT_WALLET_PACKAGE_ROOT"] = str(repo_root / "agent-wallet")
    try:
        manifest = {
            "schema_version": 1,
            "id": "com.example.codex",
            "name": "Codex Example",
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
                    "name": "discover",
                    "description": "Discover protocol data.",
                    "read_only": True,
                    "risk_level": "low",
                    "input_schema": {"type": "object", "additionalProperties": False},
                    "output_schema": {"type": "object"},
                }
            ],
        }
        ConnectorRegistry().install(manifest, source="test", enable=True)

        module = runpy.run_path(str(repo_root / "codex" / "plugins" / "agent-wallet" / "server.py"))
        definitions = {item["name"]: item for item in module["_build_tool_definitions"]()}
        connector_name = "connector__com_example_codex__discover"
        assert connector_name in definitions
        assert definitions[connector_name]["read_only"] is True
        assert connector_name in module["RESIDENT_READ_ONLY_TOOLS"]
        assert "get_wallet_balance" in definitions
    finally:
        if previous_home is None:
            os.environ.pop("OPENCLAW_HOME", None)
        else:
            os.environ["OPENCLAW_HOME"] = previous_home
        if previous_package_root is None:
            os.environ.pop("AGENT_WALLET_PACKAGE_ROOT", None)
        else:
            os.environ["AGENT_WALLET_PACKAGE_ROOT"] = previous_package_root
        shutil.rmtree(temp_home, ignore_errors=True)

    print("smoke_codex_connector_tools: ok")


if __name__ == "__main__":
    main()
