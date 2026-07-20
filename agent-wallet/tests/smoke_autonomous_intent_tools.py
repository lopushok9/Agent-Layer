"""Smoke coverage for the autonomous-mode fallback on the intent-based tools.

swap_solana_tokens, swap_evm_lifi_cross_chain_tokens,
swap_solana_lifi_cross_chain_tokens, flash_trade_open/close_position, and
all 6 Kamino tools used to call inspect_approval_token unconditionally,
which hard-requires a real host-issued token and made _require_execute_approval's
autonomous_session / agentlayer_autonomous_approve fallback unreachable dead
code for them. This verifies the new conditional branch actually authorizes
these tools once autonomy is active, and that it still denies them otherwise.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from _secret_test_utils import install_test_sealed_secrets  # noqa: E402
from agent_wallet import autonomous_permissions, autonomous_session  # noqa: E402
from agent_wallet.openclaw_adapter import OpenClawWalletAdapter  # noqa: E402
from smoke_openclaw_adapter import MainnetFakeBackend  # noqa: E402
from smoke_openclaw_evm_adapter import FakeEvmBackend  # noqa: E402


async def main() -> None:
    install_test_sealed_secrets(
        Path("/tmp/openclaw-autonomous-intent-tools-smoke"),
        boot_key="test-boot-key-for-autonomous-intent-tools-smoke",
        approval_secret="autonomous-intent-tools-smoke-secret",
    )
    autonomous_permissions.revoke_all()
    autonomous_session.stop_session()

    solana_adapter = OpenClawWalletAdapter(MainnetFakeBackend())
    evm_adapter = OpenClawWalletAdapter(FakeEvmBackend())

    swap_args = {
        "input_mint": "So11111111111111111111111111111111111111112",
        "output_mint": "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
        "amount": 0.1,
        "slippage_bps": 50,
        "purpose": "autonomous swap smoke",
    }
    swap_intent_args = {**swap_args, "valid_for_seconds": 120, "max_attempts": 3}
    lifi_solana_args = {
        "input_token": "sol",
        "destination_chain": "base",
        "output_token": "native",
        "destination_address": "0x1111111111111111111111111111111111111111",
        "amount_in_raw": "1000000",
        "slippage": 0.01,
        "purpose": "autonomous solana lifi smoke",
    }
    lifi_evm_args = {
        "token_in": "0x0000000000000000000000000000000000000000",
        "destination_chain": "base",
        "output_token": "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913",
        "destination_address": "0x3333333333333333333333333333333333333333",
        "amount_in_raw": "1000000000000000",
        "slippage": 0.01,
        "purpose": "autonomous evm lifi smoke",
    }
    flash_open_args = {
        "pool_name": "Crypto.1",
        "market_symbol": "SOL",
        "collateral_symbol": "SOL",
        "collateral_amount_raw": "100000000",
        "leverage": "5",
        "side": "long",
        "purpose": "autonomous flash open smoke",
    }
    flash_close_args = {
        "pool_name": "Crypto.1",
        "market_symbol": "SOL",
        "side": "long",
        "purpose": "autonomous flash close smoke",
    }
    kamino_lend_args = {
        "market": "FakeKaminoMarket111111111111111111111111111111",
        "reserve": "FakeKaminoReserve1111111111111111111111111111",
        "amount_ui": "1.25",
        "purpose": "autonomous kamino lend smoke",
    }
    kamino_lend_intent_args = {**kamino_lend_args, "valid_for_seconds": 90}
    kamino_earn_args = {
        "kvault": "FakeKaminoVault11111111111111111111111111111",
        "amount_ui": "2.50",
        "purpose": "autonomous kamino earn smoke",
    }
    kamino_earn_intent_args = {**kamino_earn_args, "valid_for_seconds": 75}

    cases = [
        (solana_adapter, "swap_solana_tokens", "execute", swap_args),
        (solana_adapter, "swap_solana_tokens", "intent_execute", swap_intent_args),
        (solana_adapter, "swap_solana_lifi_cross_chain_tokens", "execute", lifi_solana_args),
        (evm_adapter, "swap_evm_lifi_cross_chain_tokens", "execute", lifi_evm_args),
        (solana_adapter, "flash_trade_open_position", "execute", flash_open_args),
        (solana_adapter, "flash_trade_close_position", "execute", flash_close_args),
        (solana_adapter, "kamino_lend_deposit", "execute", kamino_lend_args),
        (solana_adapter, "kamino_lend_deposit", "intent_execute", kamino_lend_intent_args),
        (solana_adapter, "kamino_earn_deposit", "execute", kamino_earn_args),
        (solana_adapter, "kamino_earn_deposit", "intent_execute", kamino_earn_intent_args),
    ]

    # 1) Baseline: no approval_token, no autonomous_session, no
    #    agentlayer_autonomous_approve grant -> every case must still be
    #    denied exactly like before this change.
    for adapter, tool_name, mode, base_args in cases:
        result = await adapter.invoke(tool_name, {**base_args, "mode": mode})
        assert result.ok is False, f"{tool_name}/{mode} should be denied with no autonomy active, got: {result.data}"

    # 2) Enable the combined autonomous permission group -> every case must
    #    now succeed with no approval_token supplied at all.
    approved = await solana_adapter.invoke(
        "agentlayer_autonomous_approve",
        {"scope": "all", "purpose": "test intent-tool autonomous coverage", "user_intent": True},
    )
    assert approved.ok is True
    assert approved.data["active"] is True

    for adapter, tool_name, mode, base_args in cases:
        result = await adapter.invoke(tool_name, {**base_args, "mode": mode})
        assert result.ok is True, f"{tool_name}/{mode} should succeed once autonomous permission is enabled, got error: {result.error}"

    # 3) Revoke -> denied again, proving the fallback is gated by the live
    #    permission state, not a one-time bypass.
    revoked = await solana_adapter.invoke("agentlayer_autonomous_revoke", {"scope": "all"})
    assert revoked.ok is True
    assert revoked.data["active"] is False

    for adapter, tool_name, mode, base_args in cases:
        result = await adapter.invoke(tool_name, {**base_args, "mode": mode})
        assert result.ok is False, f"{tool_name}/{mode} should be denied again after revoke, got: {result.data}"

    print("smoke_autonomous_intent_tools: ok")


if __name__ == "__main__":
    asyncio.run(main())
