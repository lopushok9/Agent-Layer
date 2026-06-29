"""Smoke test that the Codex wallet bridge reuses OpenClaw defaults and read tools do not crash."""

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


def main() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    server_path = repo_root / "codex" / "plugins" / "agent-wallet" / "server.py"

    previous_env = {
        "OPENCLAW_HOME": os.environ.get("OPENCLAW_HOME"),
        "AGENT_WALLET_USER_ID": os.environ.get("AGENT_WALLET_USER_ID"),
        "OPENCLAW_AGENT_WALLET_USER_ID": os.environ.get("OPENCLAW_AGENT_WALLET_USER_ID"),
        "AGENT_WALLET_BACKEND": os.environ.get("AGENT_WALLET_BACKEND"),
        "OPENCLAW_AGENT_WALLET_BACKEND": os.environ.get("OPENCLAW_AGENT_WALLET_BACKEND"),
        "SOLANA_NETWORK": os.environ.get("SOLANA_NETWORK"),
    }

    with tempfile.TemporaryDirectory() as tmp:
        openclaw_home = Path(tmp)
        openclaw_home.mkdir(parents=True, exist_ok=True)
        config_path = openclaw_home / "openclaw.json"
        config_path.write_text(
            json.dumps(
                {
                    "plugins": {
                        "entries": {
                            "agent-wallet": {
                                "config": {
                                    "userId": "shared-openclaw-user",
                                    "backend": "solana_local",
                                    "network": "mainnet",
                                    "keypairPath": "/tmp/shared-wallet.json",
                                    "providerGatewayUrl": "https://example.invalid/gateway",
                                    "refuseMainnetWalletRecreation": True,
                                }
                            }
                        }
                    }
                }
            ),
            encoding="utf-8",
        )
        os.environ["OPENCLAW_HOME"] = str(openclaw_home)
        for name in (
            "AGENT_WALLET_USER_ID",
            "OPENCLAW_AGENT_WALLET_USER_ID",
            "AGENT_WALLET_BACKEND",
            "OPENCLAW_AGENT_WALLET_BACKEND",
            "SOLANA_NETWORK",
        ):
            os.environ.pop(name, None)

        module = _load_module(server_path, "codex_agent_wallet_server_defaults")

        assert module._user_id() == "shared-openclaw-user"
        effective = module._effective_config_for_backend("solana_local")
        assert effective["backend"] == "solana_local"
        assert effective["network"] == "mainnet"
        assert effective["keypairPath"] == "/tmp/shared-wallet.json"
        assert effective["providerGatewayUrl"] == "https://example.invalid/gateway"
        assert effective["refuseMainnetWalletRecreation"] is True

        def fake_invoke_tool(tool_name, arguments, config):
            return {
                "ok": True,
                "data": {
                    "tool": tool_name,
                    "arguments": arguments,
                    "backend": config.get("backend"),
                },
            }

        module._invoke_tool = fake_invoke_tool
        result = asyncio.run(module._handle_wallet_tool("get_wallet_balance", {}))
        assert result["tool"] == "get_wallet_balance"
        assert result["backend"] == "solana_local"

        overview = asyncio.run(module._handle_get_wallet_overview({"backend": "solana"}))
        assert overview["tool"] == "get_wallet_balance"
        assert overview["backend"] == "solana_local"
        assert overview["arguments"] == {}
        assert overview["requested_backend"] == "solana"
        assert overview["requested_network"] == "mainnet"

        base_overview = asyncio.run(module._handle_get_wallet_overview({"backend": "base"}))
        assert base_overview["tool"] == "get_wallet_balance"
        assert base_overview["backend"] == "wdk_evm_local"
        assert base_overview["arguments"] == {}
        assert base_overview["requested_backend"] == "evm"
        assert base_overview["requested_network"] == "base"

        base_switch = asyncio.run(module._handle_set_wallet_backend({"backend": "base"}))
        assert base_switch["selected_backend"] == "wdk_evm_local"
        assert base_switch["selected_network"] == "base"

    for name, value in previous_env.items():
        if value is None:
            os.environ.pop(name, None)
        else:
            os.environ[name] = value

    print("smoke_codex_plugin_openclaw_defaults: ok")


if __name__ == "__main__":
    main()
