"""Smoke test for autonomous-session execution through the OpenClaw adapter.

Proves the end-to-end flow:

1. With no session, execute requires a host approval token (legacy behavior).
2. start_autonomous_session requires a host-issued token (agent can't self-grant).
3. Once a session is active, wallet writes execute WITHOUT a per-tx token,
   bounded by the session allow-lists / spend caps / operation budget.
4. stop_autonomous_session restores per-transaction human approval.

The session record is persisted under OPENCLAW_HOME, so this also exercises
the cross-process persistence path (load -> evaluate -> persist).
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from _secret_test_utils import install_test_sealed_secrets  # noqa: E402
from agent_wallet import autonomous_session  # noqa: E402
from agent_wallet.approval import issue_approval_token  # noqa: E402
from agent_wallet.openclaw_adapter import OpenClawWalletAdapter  # noqa: E402
from agent_wallet.wallet_layer.base import AgentWalletBackend, WalletCapabilities  # noqa: E402

WALLET = "Fake11111111111111111111111111111111111111111"
RECIPIENT = "FakeRecipient1111111111111111111111111111111111"
OTHER = "OtherRecipient99999999999999999999999999999999"


class FakeBackend(AgentWalletBackend):
    name = "fake_wallet"
    network = "mainnet"

    async def get_address(self) -> str | None:
        return WALLET

    async def get_balance(self, address: str | None = None) -> dict:
        return {"chain": "solana", "network": "mainnet", "address": address or WALLET}

    def get_capabilities(self) -> WalletCapabilities:
        return WalletCapabilities(
            backend=self.name,
            chain="solana",
            custody_model="local",
            sign_only=False,
            has_signer=True,
            can_send_transaction=True,
        )

    async def preview_native_transfer(self, recipient: str, amount_native: float) -> dict:
        return {
            "chain": "solana",
            "network": "mainnet",
            "mode": "preview",
            "from_address": WALLET,
            "to_address": recipient,
            "amount_native": amount_native,
            "amount_raw": int(round(amount_native * 1_000_000_000)),  # lamports
            "source": "fake",
        }

    async def send_native_transfer(self, recipient: str, amount_native: float) -> dict:
        return {
            "chain": "solana",
            "network": "mainnet",
            "mode": "execute",
            "from_address": WALLET,
            "to_address": recipient,
            "amount_native": amount_native,
            "signature": "ok",
            "broadcasted": True,
            "confirmed": True,
            "source": "fake",
        }


def _transfer(recipient: str, amount: float) -> dict:
    return {"recipient": recipient, "amount": amount, "mode": "execute", "purpose": "smoke"}


async def main() -> None:
    install_test_sealed_secrets(
        Path("/tmp/openclaw-autonomous-session-smoke"),
        boot_key="test-boot-key-for-autonomous-session-smoke",
        approval_secret="smoke-autonomous-session-secret",
    )
    autonomous_session.stop_session()  # clean slate
    adapter = OpenClawWalletAdapter(FakeBackend())

    # 1. No session: execute is rejected without a host token.
    denied = await adapter.invoke("transfer_sol", _transfer(RECIPIENT, 0.25))
    assert denied.ok is False
    status = await adapter.invoke("get_autonomous_session", {})
    assert status.data["active"] is False

    # 2. Preview the session policy, then prove the agent cannot start it alone.
    policy = {
        "allowed_tools": ["transfer_sol"],
        "allowed_networks": ["mainnet"],
        "allow_mainnet": True,
        "allowed_recipients": [RECIPIENT],
        "max_per_tx_lamports": 500_000_000,  # 0.5 SOL
        "max_operations": 2,
    }
    preview = await adapter.invoke("start_autonomous_session", {"mode": "preview", **policy})
    assert preview.ok is True
    summary = preview.data["confirmation_summary"]

    no_token = await adapter.invoke("start_autonomous_session", {"mode": "execute", **policy})
    assert no_token.ok is False

    # 3. Host issues a token bound to the exact policy; session starts.
    token = issue_approval_token(
        tool_name="start_autonomous_session",
        network="mainnet",
        summary=summary,
        mainnet_confirmed=True,
        ttl_seconds=300,
        issued_by="smoke-host",
    )
    started = await adapter.invoke("start_autonomous_session", {"mode": "execute", "approval_token": token, **policy})
    assert started.ok is True
    assert started.data["active"] is True

    # 4. Now execution proceeds WITHOUT any per-transaction token.
    auto = await adapter.invoke("transfer_sol", _transfer(RECIPIENT, 0.25))
    assert auto.ok is True
    assert auto.data["confirmed"] is True

    # 5. Recipient not on the allow-list is rejected.
    bad_recipient = await adapter.invoke("transfer_sol", _transfer(OTHER, 0.25))
    assert bad_recipient.ok is False

    # 6. Per-transaction spend cap is enforced (0.6 SOL > 0.5 SOL cap).
    over_cap = await adapter.invoke("transfer_sol", _transfer(RECIPIENT, 0.6))
    assert over_cap.ok is False

    # 7. Operation budget: only failed ops so far besides one success; one more
    #    success exhausts the budget of 2.
    auto2 = await adapter.invoke("transfer_sol", _transfer(RECIPIENT, 0.25))
    assert auto2.ok is True
    budget_done = await adapter.invoke("transfer_sol", _transfer(RECIPIENT, 0.25))
    assert budget_done.ok is False
    assert "budget" in (budget_done.error or "").lower()

    # 8. Stopping the session restores per-transaction human approval.
    stopped = await adapter.invoke("stop_autonomous_session", {})
    assert stopped.data["active"] is False
    after_stop = await adapter.invoke("transfer_sol", _transfer(RECIPIENT, 0.25))
    assert after_stop.ok is False

    print("smoke_autonomous_session: ok")


if __name__ == "__main__":
    asyncio.run(main())
