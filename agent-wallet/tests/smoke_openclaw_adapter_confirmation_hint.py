"""Smoke test: OpenClawWalletAdapter.invoke() attaches the same next_step
hint codex/plugins/agent-wallet/server.py's _handle_wallet_tool attaches for
its own bridge.

Before this fix, that hint only existed in the Codex/Claude Code bridge --
OpenClawWalletAdapter.invoke() (the single choke point the OpenClaw Gateway
and Hermes call directly, and that the Codex/Claude Code bridge itself
reaches indirectly through the openclaw_cli.py subprocess) never attached
it. An agent using the OpenClaw runtime or Hermes directly would see
confirmation_status on an EVM send response but get no explicit guidance
to check the receipt instead of resending.

This test bypasses the real tool-dispatch logic (approval tokens, backend
resolution, etc. -- irrelevant to what's being tested here) by monkeypatching
the private _invoke_tool_dispatch method, mirroring the same technique
smoke_wallet_tool_confirmation_hint.py uses for the Codex bridge's
equivalent hook.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agent_wallet.models import AgentToolResult  # noqa: E402
from agent_wallet.openclaw_adapter import OpenClawWalletAdapter  # noqa: E402
from agent_wallet.wallet_layer.base import AgentWalletBackend, WalletCapabilities  # noqa: E402


class _StubBackend(AgentWalletBackend):
    name = "wdk_evm_local"
    chain = "evm"
    network = "base"
    sign_only = False

    async def get_address(self) -> str | None:
        return "0x1111111111111111111111111111111111111111"

    async def get_balance(self, address: str | None = None) -> dict:
        return {"chain": "evm", "network": self.network, "balance": "0"}

    def get_capabilities(self) -> WalletCapabilities:
        return WalletCapabilities(
            backend=self.name,
            chain=self.chain,
            custody_model="delegated",
            sign_only=self.sign_only,
            has_signer=True,
        )


def main() -> None:
    adapter = OpenClawWalletAdapter(_StubBackend())

    async def fake_dispatch_submitted(tool_name, arguments=None):
        return AgentToolResult(
            tool=tool_name,
            ok=True,
            data={
                "tx_hash": "0xabc123",
                "confirmation_status": "submitted",
                "confirmed": False,
            },
        )

    adapter._invoke_tool_dispatch = fake_dispatch_submitted
    submitted = asyncio.run(adapter.invoke("manage_evm_morpho_vault_position", {}))
    assert submitted.ok is True
    assert "next_step" in submitted.data, "a submitted-but-unconfirmed response must carry guidance"
    assert "0xabc123" in submitted.data["next_step"]
    assert "get_evm_transaction_receipt" in submitted.data["next_step"]
    # The original data must survive untouched alongside the added hint.
    assert submitted.data["tx_hash"] == "0xabc123"
    assert submitted.data["confirmation_status"] == "submitted"

    async def fake_dispatch_confirmed(tool_name, arguments=None):
        return AgentToolResult(
            tool=tool_name,
            ok=True,
            data={
                "tx_hash": "0xdef456",
                "confirmation_status": "confirmed",
                "confirmed": True,
            },
        )

    adapter._invoke_tool_dispatch = fake_dispatch_confirmed
    confirmed = asyncio.run(adapter.invoke("manage_evm_morpho_vault_position", {}))
    assert "next_step" not in confirmed.data, "a confirmed response must not carry the pending hint"

    async def fake_dispatch_failed(tool_name, arguments=None):
        return AgentToolResult(tool=tool_name, ok=False, error="boom", error_code="wallet_locked")

    adapter._invoke_tool_dispatch = fake_dispatch_failed
    failed = asyncio.run(adapter.invoke("manage_evm_morpho_vault_position", {}))
    assert failed.ok is False
    assert failed.data is None, "an ok=False result must be left alone"

    print("smoke_openclaw_adapter_confirmation_hint: ok")


if __name__ == "__main__":
    main()
