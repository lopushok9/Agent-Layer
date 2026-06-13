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

## What is included in this change

- `agent_wallet/autonomous_policy.py` — the engine, config, request/decision
  dataclasses. Token issuer is injectable for testing.
- `tests/smoke_autonomous_policy.py` — exercises every gate and proves an
  autonomously-issued token verifies under the standard `verify_approval_token`
  (including the mainnet-confirmation flag).

## Suggested follow-ups (not in this change)

1. Wire the engine into `openclaw_adapter`: when an autonomous session is
   configured, route execute calls through `AutonomousPolicyEngine.authorize`
   instead of demanding a host token; log every decision with its `rule`.
2. Surface a session-config tool (`start_autonomous_session` /
   `stop_autonomous_session`) so a human authorizes the *envelope* once, then
   the agent operates within it.
3. Persist the spend ledger (Redis/SQLite) for multi-instance and
   restart-survivable caps, per the note in `spending_limits.py`.
4. Extend EVM coverage by reusing `transaction_policy`-style verifiers for
   EVM calldata (allow-listed routers/spenders, approval-amount caps).
5. Emit autonomous approvals to an append-only audit trail for review.
