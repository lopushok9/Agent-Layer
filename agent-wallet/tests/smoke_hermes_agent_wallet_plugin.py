"""Smoke tests for the Hermes Agent wallet bridge plugin."""

from __future__ import annotations

import importlib.util
import base64
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
            "agent_wallet_approve",
            "agent_wallet_evm_status",
            "agent_wallet_evm_setup",
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

    blocked_approval = json.loads(
        tools.agent_wallet_approve(
            {
                "tool_name": "transfer_sol",
                "confirmation_summary": {"operation": "transfer SOL"},
                "user_confirmed": False,
            }
        )
    )
    assert blocked_approval["ok"] is False
    assert "user_confirmed=true is required" in blocked_approval["error"]

    captured.clear()
    tools.subprocess.run = fake_run
    try:
        approval = json.loads(
            tools.agent_wallet_approve(
                {
                    "tool_name": "transfer_sol",
                    "backend": "solana_local",
                    "network": "devnet",
                    "confirmation_summary": {
                        "operation": "transfer SOL",
                        "network": "devnet",
                        "amount_lamports": "1000",
                    },
                    "user_confirmed": True,
                    "ttl_seconds": 60,
                    "user_id": "hermes-test-user",
                }
            )
        )
    finally:
        tools.subprocess.run = original_run

    assert approval["ok"] is True
    assert captured["command"][1:4] == ["-m", "agent_wallet.openclaw_cli", "issue-approval"]
    assert "--summary-json" in captured["command"]
    assert "--ttl-seconds" in captured["command"]
    assert "60" in captured["command"]
    assert captured["kwargs"]["cwd"] == str(ROOT / "agent-wallet")

    class HostCompleted:
        returncode = 0
        stderr = ""

        def __init__(self, stdout: str):
            self.stdout = stdout

    host_commands = []

    def fake_host_run(command, **kwargs):
        captured["command"] = command
        captured["kwargs"] = kwargs
        host_commands.append((command, kwargs))
        script_name = Path(command[1]).name
        if script_name == "manage_openclaw_evm_wallet.py":
            return HostCompleted(
                json.dumps(
                    {
                        "ok": True,
                        "service": {"healthy": True},
                        "bindings": [],
                    }
                )
            )
        assert script_name == "bootstrap_openclaw_evm.py"
        assert kwargs["input"] == "evm-password\n"
        return HostCompleted(
            json.dumps(
                {
                    "ok": True,
                    "evm_setup": {"action": "created"},
                }
            )
        )

    captured.clear()
    tools.subprocess.run = fake_host_run
    try:
        evm_status = json.loads(
            tools.agent_wallet_evm_status(
                {
                    "user_id": "hermes-test-user",
                    "network": "base",
                }
            )
        )
        evm_setup = json.loads(
            tools.agent_wallet_evm_setup(
                {
                    "password": "evm-password",
                    "user_id": "hermes-test-user",
                    "network": "base",
                    "bind_network_pair": False,
                }
            )
        )
    finally:
        tools.subprocess.run = original_run

    assert evm_status["ok"] is True
    assert evm_setup["ok"] is True
    assert Path(host_commands[0][0][1]).name == "manage_openclaw_evm_wallet.py"
    assert Path(host_commands[1][0][1]).name == "bootstrap_openclaw_evm.py"
    assert "--password-stdin" in host_commands[1][0]
    assert "--network" in host_commands[1][0]
    assert "base" in host_commands[1][0]
    assert "--no-bind-network-pair" in host_commands[1][0]

    def fake_approval_token(summary: dict) -> str:
        payload = {
            "v": 1,
            "binding": {
                "tool": "swap_solana_tokens",
                "network": "mainnet",
                "summary": summary,
            },
        }
        encoded = base64.urlsafe_b64encode(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).decode("ascii").rstrip("=")
        return f"{encoded}.fake-signature"

    with tempfile.TemporaryDirectory() as temp_dir:
        os.environ["HERMES_HOME"] = temp_dir
        swap_summary = {
            "operation": "Swap",
            "network": "mainnet",
            "input_mint": "So11111111111111111111111111111111111111112",
            "output_mint": "444DPguaifQZ5NicFicD9Kni6emKexyqqG4dEkUaBAGS",
            "input_amount_ui": 0.003,
            "slippage_bps": 100,
            "quote_fingerprint": "preview-fingerprint",
        }
        swap_preview = {
            "chain": "solana",
            "network": "mainnet",
            "mode": "preview",
            "asset_type": "swap",
            "input_mint": swap_summary["input_mint"],
            "output_mint": swap_summary["output_mint"],
            "input_amount_ui": swap_summary["input_amount_ui"],
            "slippage_bps": swap_summary["slippage_bps"],
            "confirmation_summary": swap_summary,
            "quote_response": {"transaction": "unsigned-jupiter-order"},
            "swap_provider": "jupiter-ultra",
        }
        approved_token = {"value": ""}

        class SwapCompleted:
            returncode = 0
            stderr = ""

            def __init__(self, stdout: str):
                self.stdout = stdout

        def fake_swap_run(command, **kwargs):
            captured["command"] = command
            captured["kwargs"] = kwargs
            subcommand = command[3]
            if subcommand == "invoke":
                arguments = json.loads(command[command.index("--arguments-json") + 1])
                if arguments.get("mode") == "preview":
                    return SwapCompleted(json.dumps({"ok": True, "data": swap_preview}))
                assert arguments.get("mode") == "execute"
                assert arguments.get("_approved_preview") == swap_preview
                return SwapCompleted(json.dumps({"ok": True, "data": {"executed": True}}))
            assert subcommand == "issue-approval"
            summary = json.loads(command[command.index("--summary-json") + 1])
            assert summary["quote_fingerprint"] == "preview-fingerprint"
            assert isinstance(summary.get("_preview_digest"), str) and summary["_preview_digest"]
            approved_token["value"] = fake_approval_token(summary)
            return SwapCompleted(json.dumps({"ok": True, "approval_token": approved_token["value"]}))

        captured.clear()
        tools.subprocess.run = fake_swap_run
        try:
            cached_preview = json.loads(
                tools.agent_wallet_invoke(
                    {
                        "tool_name": "swap_solana_tokens",
                        "backend": "solana_local",
                        "network": "mainnet",
                        "arguments": {"mode": "preview"},
                    }
                )
            )
            assert cached_preview["ok"] is True
            cached_approval = json.loads(
                tools.agent_wallet_approve(
                    {
                        "tool_name": "swap_solana_tokens",
                        "backend": "solana_local",
                        "network": "mainnet",
                        "confirmation_summary": swap_summary,
                        "user_confirmed": True,
                        "mainnet_confirmed": True,
                    }
                )
            )
            assert cached_approval["ok"] is True
            cached_execute = json.loads(
                tools.agent_wallet_invoke(
                    {
                        "tool_name": "swap_solana_tokens",
                        "backend": "solana_local",
                        "network": "mainnet",
                        "arguments": {
                            "mode": "execute",
                            "approval_token": approved_token["value"],
                        },
                    }
                )
            )
            assert cached_execute["ok"] is True
        finally:
            tools.subprocess.run = original_run
            os.environ.pop("HERMES_HOME", None)

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
