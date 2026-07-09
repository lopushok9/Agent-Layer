"""Smoke test: EVM adapter exposes x402 reads to the runtime tool list."""

from __future__ import annotations

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agent_wallet.openclaw_adapter import OpenClawWalletAdapter
from agent_wallet.wallet_layer.base import AgentWalletBackend, WalletCapabilities


class _FakeEvmBackend(AgentWalletBackend):
    name = "fake-evm"

    async def get_address(self) -> str | None:
        return "0x0"

    async def get_balance(self, address: str | None = None) -> dict:
        return {"address": address or "0x0"}

    def get_capabilities(self) -> WalletCapabilities:
        return WalletCapabilities(
            backend="wdk_evm_local",
            chain="evm",
            custody_model="local",
            sign_only=True,
            has_signer=True,
            can_sign_message=True,
            can_sign_transaction=True,
            can_send_transaction=True,
        )


def main() -> None:
    adapter = OpenClawWalletAdapter(_FakeEvmBackend())
    tool_names = {tool.name for tool in adapter.list_tools()}

    assert "x402_search_services" in tool_names, tool_names
    assert "x402_get_service_details" in tool_names, tool_names
    assert "x402_preview_request" in tool_names, tool_names
    assert "x402_pay_request" in tool_names, tool_names

    print("smoke_openclaw_evm_x402_tools: ok")


if __name__ == "__main__":
    main()
