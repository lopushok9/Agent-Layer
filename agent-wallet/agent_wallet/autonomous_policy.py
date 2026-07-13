"""Autonomous execution policy engine for agent wallets.

The default execute path in :mod:`agent_wallet` is human-in-the-loop: the
host issues an approval token (see :mod:`agent_wallet.approval`) *after* a
person reviews the preview summary.  This module adds an opt-in alternative
that lets an operation execute **without a human confirming each transaction**
— but only when it passes a deterministic risk gate that the operator
configures up front.

The design mirrors the "programmable controls set in advance" model used by
Coinbase AgentKit / CDP Agentic Wallets (session caps, per-transaction
limits, allow-lists) and the ``WalletProvider`` guard pattern: a thin policy
layer wraps the existing execute path instead of replacing it.

Key safety properties:

* **Deny by default.** A freshly constructed :class:`AutonomousSessionConfig`
  approves nothing.  Every capability (tool, network, recipient, spend
  amount, mainnet access) must be explicitly enabled.
* **Same downstream verification.** When the gate passes, the engine issues
  the *exact same* signed approval token the host would issue — only the
  ``issued_by`` field differs (``"autonomous-policy"``).  Nothing downstream
  has to change or trust a new code path.
* **Bounded sessions.** Spend limits (reusing :class:`SpendingLedger`),
  operation counts, and a session TTL bound the blast radius of a
  compromised or misbehaving agent.

This module performs *no* network or signing I/O and has no dependency on a
live wallet backend, so it is cheap to unit-test in isolation.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Callable

from agent_wallet.approval import issue_approval_token
from agent_wallet.spending_limits import SpendingConfig, SpendingLedger
from agent_wallet.wallet_layer.base import WalletBackendError

#: Issuer label stamped onto autonomously-approved tokens so audit logs can
#: distinguish them from host/human approvals.
AUTONOMOUS_ISSUER = "autonomous-policy"

#: Networks treated as "real money" and therefore gated behind
#: ``allow_mainnet`` regardless of the per-tool allow-list.
MAINNET_NETWORKS = frozenset({"mainnet", "mainnet-beta", "ethereum", "base", "robinhood", "arbitrum", "optimism", "polygon"})

TokenIssuer = Callable[..., str]


def _norm_network(network: str) -> str:
    return str(network or "").strip().lower()


def _norm_addr(address: str | None) -> str:
    """Normalize an address for allow-list comparison.

    EVM ``0x`` addresses are case-insensitive, so they are lower-cased.
    Other addresses (e.g. base58 Solana keys) are compared verbatim.
    """
    value = str(address or "").strip()
    if value.lower().startswith("0x"):
        return value.lower()
    return value


@dataclass(frozen=True)
class AutonomousSessionConfig:
    """Up-front authorization envelope for a single autonomous session.

    All capabilities are off by default.  A session that is not ``enabled``,
    or whose allow-lists are empty, approves nothing.
    """

    enabled: bool = False
    allowed_tools: frozenset[str] = frozenset()
    allowed_networks: frozenset[str] = frozenset()
    #: Mainnet is gated separately from the network allow-list so an operator
    #: cannot enable "real money" execution by accident.
    allow_mainnet: bool = False
    #: Destination addresses / program ids the agent may interact with.
    allowed_recipients: frozenset[str] = frozenset()
    #: Escape hatch for flows where the destination is not known in advance
    #: (e.g. router-built swaps).  Spend caps and simulation still apply.
    allow_any_recipient: bool = False
    #: Require a passing simulation/dry-run before approving.  Strongly
    #: recommended; this is the autonomous analogue of a human eyeballing
    #: the preview.
    require_simulation: bool = True
    #: Reused spend ledger configuration (per-tx / hourly / daily / rate).
    spending: SpendingConfig = SpendingConfig()
    #: Maximum number of operations the session may approve (0 = unlimited).
    max_operations: int = 0
    #: Session lifetime in seconds (0 = no expiry).
    session_ttl_seconds: int = 0
    #: TTL applied to each issued approval token.
    approval_ttl_seconds: int = 120

    def normalized(self) -> "AutonomousSessionConfig":
        """Return a copy with networks/recipients normalized for matching."""
        return AutonomousSessionConfig(
            enabled=self.enabled,
            allowed_tools=frozenset(str(t).strip() for t in self.allowed_tools),
            allowed_networks=frozenset(_norm_network(n) for n in self.allowed_networks),
            allow_mainnet=self.allow_mainnet,
            allowed_recipients=frozenset(_norm_addr(a) for a in self.allowed_recipients),
            allow_any_recipient=self.allow_any_recipient,
            require_simulation=self.require_simulation,
            spending=self.spending,
            max_operations=self.max_operations,
            session_ttl_seconds=self.session_ttl_seconds,
            approval_ttl_seconds=self.approval_ttl_seconds,
        )


@dataclass(frozen=True)
class OperationRequest:
    """A single execute request submitted to the policy gate."""

    tool_name: str
    network: str
    #: The confirmation summary that will be bound into the approval token.
    #: It must be the same object the downstream verifier reconstructs.
    summary: dict
    #: Normalized notional spend used for limit accounting.  Callers should
    #: pass the outflow in the wallet's smallest unit (lamports/wei).  Use 0
    #: for read-shaped or zero-value operations, or ``None`` when the amount
    #: could not be determined (the session layer treats unknown spend as a
    #: hard denial whenever spend caps are configured).
    spend_amount: int | None = 0
    #: Destination address or program id, if known.
    recipient: str | None = None
    #: Whether a simulation/dry-run already succeeded for this operation.
    simulated: bool = False


@dataclass(frozen=True)
class AutonomousDecision:
    """Outcome of a policy evaluation."""

    approved: bool
    reason: str
    rule: str | None = None
    approval_token: str | None = None


@dataclass
class _SessionState:
    started_at: float
    operations: int = 0


class AutonomousPolicyEngine:
    """Deterministic risk gate that programmatically issues approval tokens.

    Construct one engine per autonomous session.  Call :meth:`evaluate` for a
    non-raising decision, or :meth:`authorize` to get a token back (raising
    :class:`WalletBackendError` on denial, matching the rest of the wallet
    layer's error contract).

    ``token_issuer`` is injectable so tests can run without a sealed approval
    secret; in production it defaults to the real
    :func:`agent_wallet.approval.issue_approval_token`.
    """

    def __init__(
        self,
        config: AutonomousSessionConfig,
        *,
        token_issuer: TokenIssuer = issue_approval_token,
        ledger: SpendingLedger | None = None,
        clock: Callable[[], float] = time.time,
        started_at: float | None = None,
        operations_used: int = 0,
    ) -> None:
        self.config = config.normalized()
        self._issuer = token_issuer
        self._ledger = ledger if ledger is not None else SpendingLedger(self.config.spending)
        self._clock = clock
        self._lock = threading.Lock()
        # ``started_at`` / ``operations_used`` are injectable so a session can
        # be rehydrated from a persisted record across processes.
        self._state = _SessionState(
            started_at=clock() if started_at is None else started_at,
            operations=int(operations_used),
        )

    # -- public API ----------------------------------------------------------

    def evaluate(self, op: OperationRequest) -> AutonomousDecision:
        """Evaluate *op* against the session policy without raising.

        On approval the returned decision carries a freshly issued, signed
        approval token bound to ``op.tool_name`` / ``op.network`` /
        ``op.summary``.
        """
        cfg = self.config
        network = _norm_network(op.network)

        with self._lock:
            # 1. Master switch.
            if not cfg.enabled:
                return self._deny("autonomous execution is disabled for this session", "enabled")

            # 2. Session lifetime.
            if cfg.session_ttl_seconds > 0:
                age = self._clock() - self._state.started_at
                if age > cfg.session_ttl_seconds:
                    return self._deny(
                        f"autonomous session expired ({age:.0f}s > {cfg.session_ttl_seconds}s)",
                        "session_ttl",
                    )

            # 3. Operation budget.
            if cfg.max_operations > 0 and self._state.operations >= cfg.max_operations:
                return self._deny(
                    f"autonomous operation budget exhausted ({cfg.max_operations} ops)",
                    "max_operations",
                )

            # 4. Tool allow-list.
            if op.tool_name not in cfg.allowed_tools:
                return self._deny(f"tool '{op.tool_name}' is not autonomously allowed", "allowed_tools")

            # 5. Network allow-list.
            if network not in cfg.allowed_networks:
                return self._deny(f"network '{network}' is not autonomously allowed", "allowed_networks")

            # 6. Mainnet gate (separate from the network allow-list).
            if network in MAINNET_NETWORKS and not cfg.allow_mainnet:
                return self._deny(
                    f"mainnet network '{network}' requires allow_mainnet for autonomous execution",
                    "allow_mainnet",
                )

            # 7. Recipient allow-list.
            if not cfg.allow_any_recipient:
                recipient = _norm_addr(op.recipient)
                if not recipient:
                    return self._deny("operation has no recipient and allow_any_recipient is false", "recipient")
                if recipient not in cfg.allowed_recipients:
                    return self._deny(f"recipient '{op.recipient}' is not on the allow-list", "recipient")

            # 8. Mandatory simulation.
            if cfg.require_simulation and not op.simulated:
                return self._deny("operation has no passing simulation and require_simulation is true", "simulation")

            # 9. Spend limits (per-tx / rate / hourly / daily). Records on pass.
            try:
                self._ledger.check_and_record(int(op.spend_amount or 0))
            except WalletBackendError as exc:
                return self._deny(str(exc), "spending")

            # 10. Issue the same signed token the host path would issue.
            try:
                token = self._issuer(
                    tool_name=op.tool_name,
                    network=op.network,
                    summary=op.summary,
                    mainnet_confirmed=network in MAINNET_NETWORKS and cfg.allow_mainnet,
                    ttl_seconds=cfg.approval_ttl_seconds,
                    issued_by=AUTONOMOUS_ISSUER,
                )
            except Exception as exc:  # noqa: BLE001 - surface issuer failures verbatim
                return self._deny(f"approval token issuance failed: {exc}", "issuer")

            self._state.operations += 1
            return AutonomousDecision(
                approved=True,
                reason="approved by autonomous policy",
                rule="approved",
                approval_token=token,
            )

    def authorize(self, op: OperationRequest) -> str:
        """Like :meth:`evaluate` but return the token or raise on denial."""
        decision = self.evaluate(op)
        if not decision.approved or not decision.approval_token:
            raise WalletBackendError(f"autonomous policy denied operation: {decision.reason}")
        return decision.approval_token

    def snapshot(self) -> dict:
        """Return a JSON-serializable view of session state for auditing."""
        with self._lock:
            return {
                "enabled": self.config.enabled,
                "operations": self._state.operations,
                "max_operations": self.config.max_operations,
                "started_at": self._state.started_at,
                "session_ttl_seconds": self.config.session_ttl_seconds,
                "allow_mainnet": self.config.allow_mainnet,
            }

    def export_spend(self) -> list[tuple[float, int]]:
        """Return the spend ledger entries so they can be persisted."""
        return self._ledger.export()

    # -- internal ------------------------------------------------------------

    @staticmethod
    def _deny(reason: str, rule: str) -> AutonomousDecision:
        return AutonomousDecision(approved=False, reason=reason, rule=rule)
