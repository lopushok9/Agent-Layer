"""Smoke test: _handle_wallet_tool attaches a next_step hint for unresolved sends.

Before this fix, a send-type tool response with confirmation_status
"submitted"/"unknown" reached the agent with no indication that the
transaction might still succeed -- a bare tx_hash sitting in the payload,
easy to miss, no guidance not to just resend. This test asserts the
generic per-tool dispatcher (the same one every wallet tool call goes
through) attaches a clear hint whenever it sees that shape, and does not
when the operation actually confirmed.
"""

from __future__ import annotations

import asyncio
import importlib.util
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

    previous_home = os.environ.get("OPENCLAW_HOME")
    with tempfile.TemporaryDirectory() as tmp:
        os.environ["OPENCLAW_HOME"] = tmp
        module = _load_module(server_path, "codex_agent_wallet_server_confirmation_hint")

        def fake_invoke_wallet_tool_blocking(tool_name, config, effective_params):
            return {
                "ok": True,
                "data": {
                    "tx_hash": "0xabc123",
                    "confirmation_status": "submitted",
                    "confirmed": False,
                },
            }

        module._invoke_wallet_tool_blocking = fake_invoke_wallet_tool_blocking
        result = asyncio.run(module._handle_wallet_tool("manage_evm_morpho_vault_position", {}))
        assert result["tx_hash"] == "0xabc123"
        assert "next_step" in result, "a submitted-but-unconfirmed response must carry guidance"
        assert "0xabc123" in result["next_step"]
        assert "get_evm_transaction_receipt" in result["next_step"]

        def fake_invoke_wallet_tool_blocking_confirmed(tool_name, config, effective_params):
            return {
                "ok": True,
                "data": {
                    "tx_hash": "0xdef456",
                    "confirmation_status": "confirmed",
                    "confirmed": True,
                },
            }

        module._invoke_wallet_tool_blocking = fake_invoke_wallet_tool_blocking_confirmed
        confirmed_result = asyncio.run(module._handle_wallet_tool("manage_evm_morpho_vault_position", {}))
        assert "next_step" not in confirmed_result, "a confirmed response must not carry the pending hint"
    if previous_home is None:
        os.environ.pop("OPENCLAW_HOME", None)
    else:
        os.environ["OPENCLAW_HOME"] = previous_home

    print("smoke_wallet_tool_confirmation_hint: ok")


if __name__ == "__main__":
    main()
