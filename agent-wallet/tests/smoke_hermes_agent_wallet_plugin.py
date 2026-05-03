"""Smoke tests for the Hermes Agent wallet bridge plugin."""

from __future__ import annotations

import importlib.util
import json
import os
import sys
import tempfile
from pathlib import Path
from types import ModuleType


ROOT = Path(__file__).resolve().parents[2]
PLUGIN_DIR = ROOT / "hermes" / "plugins" / "agent_wallet"


class FakeHermesContext:
    def __init__(self) -> None:
        self.tools: list[dict] = []

    def register_tool(self, **kwargs) -> None:
        assert kwargs["toolset"] == "agent_wallet"
        assert callable(kwargs["handler"])
        self.tools.append(kwargs)


def _load_plugin_module(name: str) -> ModuleType:
    path = PLUGIN_DIR / f"{name}.py"
    spec = importlib.util.spec_from_file_location(f"hermes_agent_wallet_{name}", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main() -> None:
    os.environ["AGENT_WALLET_PACKAGE_ROOT"] = str(ROOT / "agent-wallet")
    sys.path.insert(0, str(PLUGIN_DIR.parent))
    try:
        package = __import__("agent_wallet")
        assert callable(package.register)
        context = FakeHermesContext()
        package.register(context)
        assert [item["name"] for item in context.tools] == [
            "agent_wallet_tools",
            "agent_wallet_invoke",
        ]
    finally:
        sys.path.pop(0)
        sys.modules.pop("agent_wallet", None)

    tools = _load_plugin_module("tools")

    payload = json.loads(tools.agent_wallet_tools({"backend": "solana_local"}))
    assert payload["ok"] is True
    assert payload["backends"] == ["solana_local"]
    solana_tools = payload["tools"]["solana_local"]
    assert any(item["name"] == "get_wallet_address" for item in solana_tools)
    assert any(item["name"] == "transfer_sol" for item in solana_tools)

    blocked = json.loads(
        tools.agent_wallet_invoke(
            {
                "tool_name": "get_wallet_address",
                "config": {"masterKey": "do-not-accept"},
            }
        )
    )
    assert blocked["ok"] is False
    assert "Sensitive keys are not allowed" in blocked["error"]

    captured = {}

    class Completed:
        returncode = 0
        stdout = '{"ok": true, "data": {"address": "test"}}'
        stderr = ""

    def fake_run(command, **kwargs):
        captured["command"] = command
        captured["kwargs"] = kwargs
        return Completed()

    original_run = tools.subprocess.run
    tools.subprocess.run = fake_run
    try:
        invoked = json.loads(
            tools.agent_wallet_invoke(
                {
                    "tool_name": "get_wallet_address",
                    "backend": "solana_local",
                    "network": "devnet",
                    "arguments": {},
                    "user_id": "hermes-test-user",
                }
            )
        )
    finally:
        tools.subprocess.run = original_run

    assert invoked["ok"] is True
    assert captured["command"][1:4] == ["-m", "agent_wallet.openclaw_cli", "invoke"]
    assert "--user-id" in captured["command"]
    assert "hermes-test-user" in captured["command"]
    assert captured["kwargs"]["cwd"] == str(ROOT / "agent-wallet")

    with tempfile.TemporaryDirectory() as temp_dir:
        boot_key_file = Path(temp_dir) / "boot-key"
        boot_key_file.write_text("test-boot-key\n", encoding="utf-8")
        old_boot_key = os.environ.pop("AGENT_WALLET_BOOT_KEY", None)
        old_boot_key_file = os.environ.get("AGENT_WALLET_BOOT_KEY_FILE")
        os.environ["AGENT_WALLET_BOOT_KEY_FILE"] = str(boot_key_file)
        try:
            env = tools._cli_env(ROOT / "agent-wallet")
        finally:
            if old_boot_key is not None:
                os.environ["AGENT_WALLET_BOOT_KEY"] = old_boot_key
            else:
                os.environ.pop("AGENT_WALLET_BOOT_KEY", None)
            if old_boot_key_file is not None:
                os.environ["AGENT_WALLET_BOOT_KEY_FILE"] = old_boot_key_file
            else:
                os.environ.pop("AGENT_WALLET_BOOT_KEY_FILE", None)

    assert env["AGENT_WALLET_BOOT_KEY"] == "test-boot-key"

    print("smoke_hermes_agent_wallet_plugin: ok")


if __name__ == "__main__":
    main()
