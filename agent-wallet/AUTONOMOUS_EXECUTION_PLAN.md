# Autonomous Execution Plan

Ideas adapted from [coinbase/agentkit](https://github.com/coinbase/agentkit) and
the CDP Agentic Wallets model for **executing wallet transactions without a
human confirming each one** — gated by a deterministic, configured-up-front
risk policy.

## Motivation

Today the execute path is strictly human-in-the-loop:

- `agent_wallet/approval.py` issues a signed (HMAC-SHA256) approval token bound
  to `{tool, network, summary}`.
- A token is only minted **after a person reviews the preview** in the host UX
  (`.openclaw/extensions/agent-wallet`, `openclaw_adapter._check_execution_approval`).
- `openclaw_adapter` rejects any execute call without a valid, single-use token.

That is the right default. But some flows (recurring DCA, treasury rebalancing,
auto-repay of a lending position, paying x402 invoices under a cap) need the
agent to act **without a human clicking confirm every time** — while still being
bounded.

## What we borrowed from AgentKit / CDP

AgentKit itself does **not** ship a risk engine; its reusable idea is the
`WalletProvider` abstraction (`sign` / `sendTransaction` / `waitForTransactionReceipt`)
with a thin guard layer wrapped around `sendTransaction`. The risk controls live
in CDP Agentic Wallets as **programmable controls set in advance**: session caps,
per-transaction limits, allow-lists, and per-action authorization.

We map those concepts onto the primitives this repo already has, instead of
importing any Coinbase code:

| AgentKit / CDP concept            | Existing Agent-Layer primitive                          |
| --------------------------------- | ------------------------------------------------------- |
| Programmable controls / policy    | new `autonomous_policy.AutonomousPolicyEngine`          |
| Session cap / per-tx / rate limit | `spending_limits.SpendingLedger` (reused)               |
| Allow-lists (token/program/dest)  | `transaction_policy.verify_provider_*` + recipient list |
| Authorization artifact            | `approval.issue_approval_token` (reused, unchanged)     |
| Mandatory simulation before send  | existing `preview`/`prepare` simulation deltas          |

## Design

A new module — `agent_wallet/autonomous_policy.py` — adds a **programmatic
approval authority**. When an operation passes the gate, the engine issues the
*exact same* signed approval token the host would issue; only `issued_by`
differs (`"autonomous-policy"`). **Nothing downstream changes**: the same
`verify_approval_token`, the same single-use enforcement, the same spend ledger.

```
preview (risk-free)
  -> simulate / verify deltas (transaction_policy)
  -> AutonomousPolicyEngine.evaluate(op)        # deny-by-default gate
       1. enabled?                              # master switch
       2. session not expired?
       3. operation budget left?
       4. tool on allow-list?
       5. network on allow-list?
       6. mainnet gated behind allow_mainnet?
       7. recipient on allow-list (or allow_any)?
       8. simulation present (require_simulation)?
       9. spend within per-tx / rate / hourly / daily caps?
  -> issue_approval_token(issued_by="autonomous-policy")
  -> existing execute path (unchanged)
```

### Safety properties

- **Deny by default.** An empty `AutonomousSessionConfig` approves nothing.
  Every capability is opt-in.
- **Mainnet is double-gated.** Real-money networks require `allow_mainnet=True`
  on top of being on the network allow-list, so they can't be enabled by
  accident.
- **Same trust boundary.** Autonomous tokens are indistinguishable downstream
  except for an audit label, so we don't introduce a second, weaker code path.
- **Bounded blast radius.** `SpendingLedger` caps (per-tx / hourly / daily /
  rate), an operation budget, and a session TTL limit what a compromised agent
  can do before a human notices.
- **No new I/O.** The engine performs no network or signing calls and is fully
  unit-testable (`tests/smoke_autonomous_policy.py`).

## What is included

- `agent_wallet/autonomous_policy.py` — the engine, config, request/decision
  dataclasses. Token issuer, clock, started_at, and operation count are
  injectable so a session can be rehydrated across processes.
- `agent_wallet/autonomous_session.py` — persistent session store under
  `OPENCLAW_HOME` (the CLI runs one subprocess per tool call, so the envelope
  must survive on disk). Provides `start_session` / `stop_session` /
  `session_status` / `authorize_operation`, with fail-closed handling when a
  spend amount can't be verified under configured caps.
- `agent_wallet/spending_limits.py` — `SpendingLedger` now accepts an injectable
  `clock` and `entries`, plus an `export()` method, so caps can be persisted and
  enforced with wall-clock time across processes (default behavior unchanged).
- `agent_wallet/openclaw_adapter.py`:
  - autonomous fallback wired into the single approval choke point
    (`_require_execute_approval`): when no host token is present but a session is
    active, the engine mints the same signed token and the downstream verify /
    single-use / execute path is unchanged.
  - new tools `start_autonomous_session` (host-token gated — an agent cannot
    self-grant), `stop_autonomous_session` (always allowed), and
    `get_autonomous_session` (read-only status).
- Tests: `tests/smoke_autonomous_policy.py` (every gate + real-token roundtrip)
  and `tests/smoke_autonomous_session.py` (end-to-end through the adapter,
  including persistence, allow-lists, spend caps, and operation budget).

## Suggested follow-ups (not in this change)

1. Persist the spend ledger and single-use nonce registry in Redis/SQLite for
   multi-instance and restart-survivable enforcement, per the notes in
   `spending_limits.py` / `nonce_registry.py`.
2. Extend EVM coverage by reusing `transaction_policy`-style verifiers for EVM
   calldata (allow-listed routers/spenders, approval-amount caps).
3. Emit autonomous approvals to an append-only audit trail for review.
