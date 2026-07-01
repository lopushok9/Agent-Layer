"""Smoke test that the Codex wallet plugin bundle is present and wired consistently."""

from __future__ import annotations

import json
from pathlib import Path


def main() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    plugin_root = repo_root / "codex" / "plugins" / "agent-wallet"
    manifest_path = plugin_root / ".codex-plugin" / "plugin.json"
    mcp_path = plugin_root / ".mcp.json"
    server_path = plugin_root / "server.py"
    script_path = plugin_root / "scripts" / "run_mcp.sh"
    wallet_operator_path = plugin_root / "skills" / "wallet-operator" / "SKILL.md"
    wallet_sol_path = plugin_root / "skills" / "wallet-sol" / "SKILL.md"

    assert manifest_path.exists(), "Codex plugin manifest is missing"
    assert mcp_path.exists(), "Codex plugin MCP config is missing"
    assert server_path.exists(), "Codex plugin server is missing"
    assert script_path.exists(), "Codex plugin launch script is missing"
    assert wallet_operator_path.exists(), "Codex wallet operator skill is missing"
    assert wallet_sol_path.exists(), "Codex wallet-sol skill is missing"

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    mcp = json.loads(mcp_path.read_text(encoding="utf-8"))

    assert manifest["name"] == "agent-wallet"
    assert manifest["mcpServers"] == "./.mcp.json"
    assert manifest["skills"] == "./skills/"
    assert "interface" in manifest and isinstance(manifest["interface"], dict)
    assert "agent-wallet" in mcp.get("mcpServers", {})
    assert mcp["mcpServers"]["agent-wallet"]["command"] == "sh"

    package_json = json.loads((repo_root / "package.json").read_text(encoding="utf-8"))
    files = package_json.get("files", [])
    assert "codex/plugins/agent-wallet/" in files

    print("smoke_codex_plugin_contracts: ok")


if __name__ == "__main__":
    main()
