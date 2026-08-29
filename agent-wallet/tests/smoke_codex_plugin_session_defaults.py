"""Smoke test: a wallet/network switch survives into the next MCP session.

set_wallet_backend/set_evm_network previously only mutated module-level
globals scoped to one server.py process — the Codex/Claude Code MCP bridge
Claude Code (and Codex) restart per session, so every new session reset back
to the static openclaw.json/env default regardless of what the user picked
last time. This test simulates two separate sessions (two independent module
loads sharing one OPENCLAW_HOME) and asserts the second one starts on
whatever the first one selected.
"""

from __future__ import annotations

import asyncio
import importlib.util
import json
import os
import tempfile
from pathlib import Path


def _load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _stub_invoke_tool(module) -> None:
    def fake_invoke_tool(tool_name, arguments, config):
        return {"ok": True, "data": {"tool": tool_name, "arguments": arguments}}

    module._invoke_tool = fake_invoke_tool


def main() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    server_path = repo_root / "codex" / "plugins" / "agent-wallet" / "server.py"

    previous_env = {
        "OPENCLAW_HOME": os.environ.get("OPENCLAW_HOME"),
        "AGENT_WALLET_BACKEND": os.environ.get("AGENT_WALLET_BACKEND"),
        "OPENCLAW_AGENT_WALLET_BACKEND": os.environ.get("OPENCLAW_AGENT_WALLET_BACKEND"),
        "WDK_EVM_NETWORK": os.environ.get("WDK_EVM_NETWORK"),
        "SOLANA_NETWORK": os.environ.get("SOLANA_NETWORK"),
    }

    with tempfile.TemporaryDirectory() as tmp:
        openclaw_home = Path(tmp)
        os.environ["OPENCLAW_HOME"] = str(openclaw_home)
        for name in (
            "AGENT_WALLET_BACKEND",
            "OPENCLAW_AGENT_WALLET_BACKEND",
            "WDK_EVM_NETWORK",
            "SOLANA_NETWORK",
        ):
            os.environ.pop(name, None)

        # --- "session 1": no config file yet, so the hardcoded fallback applies.
        session_one = _load_module(server_path, "codex_agent_wallet_server_session_one")
        assert session_one._default_backend() == "solana_local"
        assert session_one._default_evm_network() is None
        assert session_one.selected_evm_network is None

        _stub_invoke_tool(session_one)
        switch = asyncio.run(session_one._handle_set_evm_network({"network": "base"}))
        assert switch["selected_network"] == "base"
        assert switch["remembered_as_default"] is True

        session_defaults_path = openclaw_home / "agent-wallet" / "session-defaults.json"
        assert session_defaults_path.exists()
        on_disk = json.loads(session_defaults_path.read_text(encoding="utf-8"))
        assert on_disk == {"backend": "wdk_evm_local", "evm_network": "base"}

        # --- "session 2": a fresh module load (globals reset), same OPENCLAW_HOME.
        # Nobody called set_evm_network in this "session" yet, but the default
        # must already be base, not the hardcoded ethereum/mainnet fallback.
        session_two = _load_module(server_path, "codex_agent_wallet_server_session_two")
        assert session_two.selected_evm_network is None, "globals must not leak across module loads"
        assert session_two._default_backend() == "wdk_evm_local"
        assert session_two._default_evm_network() == "base"
        assert session_two._network_for_backend("wdk_evm_local") == "base"

        overview_backend = session_two._active_backend_for_tool("get_evm_balance")
        assert overview_backend == "wdk_evm_local"

        # An explicit env override still wins over the remembered default.
        os.environ["WDK_EVM_NETWORK"] = "ethereum"
        assert session_two._default_evm_network() == "ethereum"
        os.environ.pop("WDK_EVM_NETWORK", None)

        # Switching again in "session 2" updates what "session 3" would see.
        _stub_invoke_tool(session_two)
        asyncio.run(session_two._handle_set_wallet_backend({"backend": "robinhood"}))
        session_three = _load_module(server_path, "codex_agent_wallet_server_session_three")
        assert session_three._default_backend() == "wdk_evm_local"
        assert session_three._default_evm_network() == "robinhood"

    for name, value in previous_env.items():
        if value is None:
            os.environ.pop(name, None)
        else:
            os.environ[name] = value

    print("smoke_codex_plugin_session_defaults: ok")


if __name__ == "__main__":
    main()
