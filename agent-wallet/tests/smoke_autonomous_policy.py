"""Smoke test for the autonomous execution policy engine.

Part 1 exercises every gate in isolation with an injected token issuer, so it
needs no sealed approval secret and performs no I/O.

Part 2 wires the engine to the *real* ``issue_approval_token`` and proves the
autonomously-issued token is accepted by the same ``verify_approval_token``
the human-in-the-loop path uses.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from _secret_test_utils import install_test_sealed_secrets  # noqa: E402
from agent_wallet.approval import verify_approval_token  # noqa: E402
from agent_wallet.autonomous_policy import (  # noqa: E402
    AUTONOMOUS_ISSUER,
    AutonomousPolicyEngine,
    AutonomousSessionConfig,
    OperationRequest,
)
from agent_wallet.spending_limits import SpendingConfig  # noqa: E402
from agent_wallet.wallet_layer.base import WalletBackendError  # noqa: E402

RECIPIENT = "FakeRecipient1111111111111111111111111111111111"
SUMMARY = {"to": RECIPIENT, "amount": "0.25", "asset": "SOL"}


def _fake_issuer(**kwargs) -> str:
    # Echo the binding so assertions can confirm the engine passed it through.
    assert kwargs["issued_by"] == AUTONOMOUS_ISSUER
    return f"tok::{kwargs['tool_name']}::{kwargs['network']}::{kwargs['ttl_seconds']}"


def _base_config(**overrides) -> AutonomousSessionConfig:
    params = dict(
        enabled=True,
        allowed_tools=frozenset({"transfer_sol"}),
        allowed_networks=frozenset({"devnet"}),
        allowed_recipients=frozenset({RECIPIENT}),
        require_simulation=True,
        approval_ttl_seconds=120,
    )
    params.update(overrides)
    return AutonomousSessionConfig(**params)


def _op(**overrides) -> OperationRequest:
    params = dict(
        tool_name="transfer_sol",
        network="devnet",
        summary=SUMMARY,
        spend_amount=0,
        recipient=RECIPIENT,
        simulated=True,
    )
    params.update(overrides)
    return OperationRequest(**params)


def test_gates() -> None:
    # Disabled by default => deny everything.
    disabled = AutonomousPolicyEngine(AutonomousSessionConfig(), token_issuer=_fake_issuer)
    assert disabled.evaluate(_op()).approved is False

    # Happy path.
    engine = AutonomousPolicyEngine(_base_config(), token_issuer=_fake_issuer)
    ok = engine.evaluate(_op())
    assert ok.approved is True
    assert ok.approval_token == "tok::transfer_sol::devnet::120"

    # Tool not allow-listed.
    assert AutonomousPolicyEngine(_base_config(), token_issuer=_fake_issuer).evaluate(
        _op(tool_name="swap_evm_tokens")
    ).rule == "allowed_tools"

    # Network not allow-listed.
    assert AutonomousPolicyEngine(_base_config(), token_issuer=_fake_issuer).evaluate(
        _op(network="testnet")
    ).rule == "allowed_networks"

    # Mainnet gated even if it is on the network allow-list.
    mainnet_cfg = _base_config(allowed_networks=frozenset({"mainnet"}), allow_mainnet=False)
    assert AutonomousPolicyEngine(mainnet_cfg, token_issuer=_fake_issuer).evaluate(
        _op(network="mainnet")
    ).rule == "allow_mainnet"

    # Mainnet allowed when explicitly enabled.
    mainnet_ok = _base_config(allowed_networks=frozenset({"mainnet"}), allow_mainnet=True)
    assert AutonomousPolicyEngine(mainnet_ok, token_issuer=_fake_issuer).evaluate(
        _op(network="mainnet")
    ).approved is True

    # Recipient not allow-listed.
    assert AutonomousPolicyEngine(_base_config(), token_issuer=_fake_issuer).evaluate(
        _op(recipient="OtherRecipient99999999999999999999999999999999")
    ).rule == "recipient"

    # Missing recipient with allow_any_recipient disabled.
    assert AutonomousPolicyEngine(_base_config(), token_issuer=_fake_issuer).evaluate(
        _op(recipient=None)
    ).rule == "recipient"

    # allow_any_recipient bypasses the recipient gate.
    any_recipient = _base_config(allow_any_recipient=True)
    assert AutonomousPolicyEngine(any_recipient, token_issuer=_fake_issuer).evaluate(
        _op(recipient=None)
    ).approved is True

    # Simulation required but absent.
    assert AutonomousPolicyEngine(_base_config(), token_issuer=_fake_issuer).evaluate(
        _op(simulated=False)
    ).rule == "simulation"

    # Per-transaction spend cap.
    capped = _base_config(spending=SpendingConfig(max_per_tx_lamports=1_000))
    assert AutonomousPolicyEngine(capped, token_issuer=_fake_issuer).evaluate(
        _op(spend_amount=2_000)
    ).rule == "spending"

    # Operation budget enforced across calls.
    budgeted = AutonomousPolicyEngine(_base_config(max_operations=1), token_issuer=_fake_issuer)
    assert budgeted.evaluate(_op()).approved is True
    second = budgeted.evaluate(_op())
    assert second.approved is False
    assert second.rule == "max_operations"

    # Daily cap accumulates across approved operations.
    daily = AutonomousPolicyEngine(
        _base_config(spending=SpendingConfig(max_daily_lamports=1_500)),
        token_issuer=_fake_issuer,
    )
    assert daily.evaluate(_op(spend_amount=1_000)).approved is True
    over = daily.evaluate(_op(spend_amount=1_000))
    assert over.approved is False
    assert over.rule == "spending"

    # authorize() raises on denial.
    try:
        AutonomousPolicyEngine(_base_config(), token_issuer=_fake_issuer).authorize(_op(simulated=False))
    except WalletBackendError as exc:
        assert "autonomous policy denied" in str(exc)
    else:  # pragma: no cover - defensive
        raise AssertionError("authorize() should have raised on a denied operation")


def test_real_token_roundtrip() -> None:
    install_test_sealed_secrets(
        Path("/tmp/openclaw-autonomous-policy-smoke"),
        boot_key="test-boot-key-for-autonomous-policy-smoke",
        approval_secret="smoke-autonomous-secret",
    )
    # Default issuer == the real issue_approval_token.
    engine = AutonomousPolicyEngine(
        _base_config(allowed_networks=frozenset({"mainnet"}), allow_mainnet=True)
    )
    token = engine.authorize(_op(network="mainnet"))

    # The token the engine produced must verify under the standard path,
    # including the mainnet-confirmation flag the policy asserts on our behalf.
    payload = verify_approval_token(
        token,
        tool_name="transfer_sol",
        network="mainnet",
        summary=SUMMARY,
        require_mainnet_confirmation=True,
    )
    assert payload["issued_by"] == AUTONOMOUS_ISSUER
    assert payload["mainnet_confirmed"] is True


def main() -> None:
    test_gates()
    test_real_token_roundtrip()
    print("smoke_autonomous_policy: ok")


if __name__ == "__main__":
    main()
