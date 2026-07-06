"""The resident read worker serves every adapter-declared read-only tool.

Previously only get_wallet_balance/get_wallet_portfolio ran in the resident
worker; every other read (quotes, markets, positions, fee rates) paid a full
cold subprocess (interpreter + imports + onboarding). Both the CLI worker
gate and the bridge routing set now derive from the adapter's read_only tool
specs.
"""
from __future__ import annotations

import asyncio
import importlib.util
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

EXPECTED_READ_TOOLS = {
    "get_wallet_balance",
    "get_wallet_portfolio",
    "get_evm_fee_rates",
    "get_solana_token_prices",
    "get_kamino_lend_markets",
    "get_evm_swap_quote",
    "get_lifi_quote",
}
WRITE_TOOLS = {"swap_evm_tokens", "transfer_sol", "swap_solana_tokens", "x402_pay_request"}


def _load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _FakeResult:
    def __init__(self, payload):
        self._payload = payload

    def model_dump(self):
        return self._payload


class _FakeSpec:
    def __init__(self, name, read_only):
        self._payload = {"name": name, "read_only": read_only, "description": name}

    def model_dump(self):
        return dict(self._payload)


class _FakeAdapter:
    def __init__(self):
        self.invoked: list[str] = []

    def list_tools(self):
        return [
            _FakeSpec("get_evm_fee_rates", True),
            _FakeSpec("get_wallet_balance", True),
            _FakeSpec("swap_evm_tokens", False),
        ]

    async def invoke(self, tool_name, arguments):
        self.invoked.append(tool_name)
        return _FakeResult({"ok": True, "data": {"tool": tool_name}})


class _FakeContext:
    def __init__(self):
        self.adapter = _FakeAdapter()


def check_cli_worker_gate() -> None:
    from agent_wallet import openclaw_cli

    context = _FakeContext()
    allowed = openclaw_cli._read_only_tool_names(context)
    assert "get_evm_fee_rates" in allowed, "adapter read-only tools must be allowed"
    assert "swap_evm_tokens" not in allowed, "write tools must never be allowed"

    payload = asyncio.run(
        openclaw_cli._run_read_worker_tool(
            context, {"tool": "get_evm_fee_rates", "arguments": {}}, allowed
        )
    )
    assert payload["data"]["tool"] == "get_evm_fee_rates"

    try:
        asyncio.run(
            openclaw_cli._run_read_worker_tool(
                context, {"tool": "swap_evm_tokens", "arguments": {}}, allowed
            )
        )
        raise AssertionError("write tool must be rejected by the read worker")
    except Exception as exc:
        assert "read-only" in str(exc), str(exc)


def check_bridge_routing() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    server_path = repo_root / "codex" / "plugins" / "agent-wallet" / "server.py"
    with tempfile.TemporaryDirectory() as tmp:
        os.environ["OPENCLAW_HOME"] = tmp
        os.environ["AGENT_WALLET_PREWARM_READ_WORKER"] = "0"
        module = _load_module(server_path, "codex_agent_wallet_server_expanded_reads")

        definitions = module._build_tool_definitions()
        names = {spec["name"] for spec in definitions}
        assert EXPECTED_READ_TOOLS <= names, EXPECTED_READ_TOOLS - names

        resident = module.RESIDENT_READ_ONLY_TOOLS
        missing = EXPECTED_READ_TOOLS - resident
        assert not missing, f"read-only tools missing from resident routing: {missing}"
        leaked = WRITE_TOOLS & resident
        assert not leaked, f"write tools must never be resident-routed: {leaked}"


def main() -> None:
    check_cli_worker_gate()
    check_bridge_routing()
    print("smoke_read_worker_expanded_tools OK")


if __name__ == "__main__":
    main()
