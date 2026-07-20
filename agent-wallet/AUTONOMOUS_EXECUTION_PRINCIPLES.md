# Autonomous Execution: Principles

This note explains the model behind autonomous (no per-transaction human
confirmation) wallet execution in Agent-Layer, the ideas borrowed from
Coinbase's CDP / AgentKit, and how they map onto this codebase.

## The question

> Can an agent execute DeFi transactions/operations **without a human
> confirming each one**? And if we port Coinbase's model, do we get the same?

Short answer: **yes** — provided a human authorizes the *boundaries* up front.
The agent then acts autonomously **inside** those boundaries.

## What Coinbase's CDP model actually does

CDP **Agentic Wallets** let an AI agent sign and broadcast transactions
(swaps, transfers, yield, payments) **without a human clicking "confirm" on
every transaction**. The safety does **not** come from confirming each action;
it comes from **programmable controls set in advance**:

- **session caps** — how much may be spent over a session,
- **per-transaction limits** — the size of any single transaction,
- **allow-lists** — which destinations / actions are permitted,
- **per-action authorization** — which actions still need extra approval.

So the human approves an **envelope of authority once**, not every transaction.
Inside that envelope the agent is autonomous; signing happens on CDP's
MPC-secured wallet.

### Important nuance

The open-source `coinbase/agentkit` repository does **not** contain a risk
engine. Its reusable idea is the `WalletProvider` abstraction
(`sign` / `sendTransaction` / `waitForTransactionReceipt`) with a thin guard
around `sendTransaction`. The actual limits/allow-lists live in the **CDP
Agentic Wallets** product (hosted, tied to Coinbase's MPC wallet). You can port
the **model**, not literal files.

## Can we get the same in Agent-Layer? Yes — and we do

The model maps cleanly onto primitives this repo already has. No Coinbase code
is imported; signing stays in the local wdk wallet, not on a third party.

| CDP / AgentKit concept            | Agent-Layer implementation                              |
| --------------------------------- | ------------------------------------------------------- |
| Human authorizes an envelope once | `start_autonomous_session` (gated by a host token)      |
| Programmable controls / policy    | `autonomous_policy.AutonomousPolicyEngine`              |
| Session cap / per-tx / rate limit | `spending_limits.SpendingLedger` (reused)               |
| Allow-lists (tool / network / to) | `AutonomousSessionConfig` allow-lists                   |
| Mandatory simulation before send  | existing `preview` / `prepare` simulation path          |
| Authorization artifact            | `approval.issue_approval_token` (reused, unchanged)     |
| Signing                           | local wdk EVM / Solana / BTC wallet (unchanged)         |

## How it works here

The default execute path is human-in-the-loop: `approval.py` mints a signed
(HMAC-SHA256) token bound to `{tool, network, summary}`, and the host issues it
only after a person reviews the preview. Autonomous mode adds a **programmatic
approval authority**:

```
human starts a session once  ──>  start_autonomous_session (host token)
                                   persists an envelope under OPENCLAW_HOME

agent calls a write tool (mode=execute, no token)
   └─> preview/quote + simulation (existing path)
   └─> AutonomousPolicyEngine.evaluate(op)        # deny-by-default gate
         1. session enabled?
         2. session not expired?
         3. operation budget remaining?
         4. tool on allow-list?
         5. network on allow-list?
         6. mainnet double-gated (allow_mainnet)?
         7. recipient on allow-list (or allow_any_recipient)?
         8. simulation present (require_simulation)?
         9. spend within per-tx / rate / hourly / daily caps?
   └─> issue the SAME signed token (issued_by="autonomous-policy")
   └─> existing verify + single-use + execute (unchanged downstream)
```

Because the engine mints the *same* token the host would, **nothing downstream
changes** — same `verify_approval_token`, same single-use registry, same spend
ledger. There is no second, weaker code path.

## Safety principles

1. **Deny by default.** An empty config approves nothing; every capability is
   opt-in.
2. **The human authorizes the envelope, not each tx.** Starting a session
   requires a host-issued token bound to the exact policy, so an agent cannot
   widen its own authority. Stopping a session is always allowed (it only
   reduces authority).
3. **Mainnet is double-gated.** Real-money networks require `allow_mainnet=true`
   on top of being on the network allow-list.
4. **Same trust boundary.** Autonomous tokens are indistinguishable downstream
   except for an audit label (`issued_by`).
5. **Bounded blast radius.** Spend caps + operation budget + session TTL limit
   what a compromised or misbehaving agent can do.
6. **Fail closed.** If spend caps are configured but the spend amount for an
   operation cannot be verified, the operation is denied.
7. **Local signing.** Keys never leave the local wdk wallet; we do not depend on
   a hosted custodian.

## Example

```jsonc
// 1. Preview the policy (agent or host)
start_autonomous_session {
  "mode": "preview",
  "allowed_tools": ["swap_evm_tokens", "manage_evm_aave_position"],
  "allowed_networks": ["base"],
  "allow_mainnet": true,
  "allow_any_recipient": true,        // router-built swaps
  "max_per_tx_lamports": 200000000,   // per-tx cap (smallest units)
  "max_daily_lamports": 1000000000,   // daily cap
  "max_operations": 20,
  "session_ttl_seconds": 3600
}

// 2. Host reviews the returned confirmation_summary and issues a token,
//    then starts the session:
start_autonomous_session { "mode": "execute", "approval_token": "<host token>", ...same policy... }

// 3. The agent now runs swaps / Aave actions on Base for up to an hour,
//    within the caps, with no further human clicks — until stopped:
stop_autonomous_session {}
```

## Status / scope

Implemented: the policy engine, persistent session store, the
`start_/stop_/get_autonomous_session` tools, and the autonomous fallback in the
adapter's single approval choke point (`_require_execute_approval`).

Suggested follow-ups: persist the spend ledger in Redis/SQLite for multi-instance
deployments, an append-only audit log of autonomous decisions, and EVM-calldata
verifiers (allow-listed routers/spenders, approval-amount caps) analogous to the
existing Solana `transaction_policy` checks.

## High-trust permission mode

There is also a separate, less restrictive UX model for users who explicitly
want coding-CLI-style permissions: approve a capability once, then let the
agent use it without a per-transaction prompt. This is intentionally **not**
the same as `start_autonomous_session`; it has no spending caps, token
allow-list, router allow-list, or session TTL.

Current scope:

- `agentlayer_autonomous_approve { "scope": "base_swaps", ... }`
- `agentlayer_autonomous_revoke { "scope": "base_swaps" }`
- `agentlayer_autonomous_approve { "scope": "defi_tools", ... }`
- `agentlayer_autonomous_revoke { "scope": "defi_tools" }`
- `agentlayer_autonomous_status`
- `base_swaps` and `defi_tools` are compatibility scope labels for one
  combined autonomous permission group; approving either enables both, and
  revoking either disables both
- `swap_evm_tokens` (Velora) and `swap_evm_uniswap_tokens` (Base only) and the
  supported EVM DeFi management tools (Aave, Morpho vault/market, Lido
  staking/withdrawal on `base`/`ethereum`/`robinhood`) have their own
  dedicated pre-authorization step (`_authorize_base_swap_permission` /
  `_authorize_defi_permission`) that fetches a fresh preview/quote before
  minting the approval token, ahead of reaching `_require_execute_approval`
- every other write tool that funnels through the shared choke point,
  `_require_execute_approval` (transfers, bridges, Solana swaps, staking,
  x402 payments, generic contract calls, and the tools above once they reach
  it) is covered by the same combined group as a fallback, alongside the
  `autonomous_session` fallback -- enabling the group therefore covers every
  wallet write tool, not just Base swaps and EVM DeFi

When enabled, a covered execute call with no `approval_token` fetches a fresh
preview/quote, builds the exact confirmation summary, issues the same signed
approval token internally (`issued_by="autonomous-permission:*"`), then runs
the existing verification and send path. This preserves exact operation binding
while removing the host confirmation step for the combined permission group.

This mode is high-trust by design, and unbounded by design: there is no
dollar cap, allow-list, or TTL anywhere in this path. It is appropriate only
when the user wants the agent to have full practical authority over every
wallet write tool until explicitly revoked. Users who want a bounded grant
(spend caps, tool/network/recipient allow-lists, a session TTL) should use
`start_autonomous_session` instead.
