# AgentLayer Treasury — agentic commerce on Airwallex

**Agents spend from one shared business account, each under a budget the human operator sets.
Stablecoin (x402) first; when a merchant only takes cards, the agent gets a single-use Airwallex
card whose limits *are* the approved purchase. Card numbers never reach the model.**

Built for the Airwallex Agentic Banking Hackathon. Runs entirely on the Airwallex sandbox.

---

## The problem

AI agents now do real business tasks: buying data, compute, SaaS seats, paying vendors. Giving an agent
a company card or an API key with no limits is reckless. Making a human approve every purchase defeats
the point. And most merchants still don't accept agent-native payments (x402), so a stablecoin-only agent
gets stuck at the first card-only checkout.

## What we built

| | |
|---|---|
| **Shared account, per-agent budgets** | The operator gives each agent a budget, a per-transaction limit, an auto-approve threshold, allowed merchant categories and allowed rails. Spent and reserved amounts are tracked per agent. |
| **Decisions in code, not prompts** | Every request goes through a deterministic policy: `auto_approve`, `needs_approval` (with reasons such as `over_budget`, `above_auto_approve_limit`, `merchant_category_not_allowed`, `below_reserve_floor`) or `deny`. The model proposes and explains; it never decides whether money moves. |
| **x402 first, fiat fallback** | The treasury probes the merchant. An HTTP 402 with x402 terms → the agent pays USDC on Base with the wallet's x402 tools. Anything else → an Airwallex card. |
| **Policy-bound single-use cards** | Each approved card purchase gets its own virtual card: `allowed_transaction_count: SINGLE`, PER_TRANSACTION and ALL_TIME limits equal to the approved amount, a merchant-category lock, and a 60-minute `active_to` window, tagged with `metadata.agent_id`. **Airwallex enforces the decision on the card network**: an overcharge returns `LIMIT_EXCEEDED`, a wrong merchant `MERCHANT_CATEGORY_NOT_ALLOWED`, and a reused card is refused. |
| **PCI-safe card use by agents** | `GET /issuing/cards/{id}/details` goes straight into our local encrypted **CardVault** (libsodium sealed boxes, private key in the macOS login Keychain). The agent only gets `last4` and a `vault_reference`, and checks out through `use_saved_card` (a fixed HTTPS executor or a managed Kernel browser that fills the card fields itself). Airwallex's own agent-cards reference build lists exactly this as a critical gap: *"no documented PCI-safe credential flow for autonomous agents"*. |
| **Operator in control** | A CLI and a local web dashboard: budgets and limits, a live payments feed, an approval queue (approve issues the card), pause, which **freezes every live card at Airwallex**, Issuing reconciliation and an audit log. |
| **Idle cash → yield** | `treasury idle` computes the cash that is neither reserved on cards, committed to agent budgets nor part of the reserve floor. That cash can sit in the wallet's yield vault (Morpho USDC on Base) until agents need it. |

## Architecture

```
            ┌──────────── Operator (human) ────────────┐
            │  treasury CLI  ·  dashboard 127.0.0.1    │
            │  budgets · limits · approve/deny · pause │
            └───────────────────┬──────────────────────┘
                                │
 Agent (Claude Code / Codex /   ▼
 OpenClaw / Hermes)      ┌──────────────────────────────┐     Airwallex sandbox
  treasury_request_ ────►│  Treasury (policy + ledger)  │──► Issuing: DELEGATE cardholder,
  payment                │  decide() in code            │     cards/create (authorization_controls,
                         │  x402 probe → rail           │     metadata.agent_id), cards/{id}/details,
                         └──────┬───────────────┬───────┘     cards/{id}/update (freeze/close),
                      x402 rail │               │ card rail   issuing/transactions,
                                ▼               ▼             simulation/issuing/create,
                   wallet x402 tools     CardVault (sealed)   balances/current
                   USDC on Base          vault_reference ──► use_saved_card / Kernel checkout
```

Code: [`agent-wallet/agent_wallet/airwallex/`](agent-wallet/agent_wallet/airwallex)

| File | Role |
|---|---|
| `client.py` | Airwallex REST client: token cache, `x-api-version: 2026-08-21`, sandbox by default (production is refused unless explicitly enabled) |
| `issuing.py` | Cardholder, card creation with `authorization_controls`, sensitive details → vault, freeze/close, transactions, sandbox authorization simulation |
| `treasury.py` | Shared account state: agents, policy `decide()`, payment state machine, reservations, approval queue, audit log |
| `service.py` | Orchestration: x402 probe, routing, issuance with a reserve-floor check, settlement, reconciliation, idle funds |
| `tools.py` | Agent-facing MCP tools (`treasury_*`). Approve/limits/pause are **not** exposed to agents. |
| `cli.py`, `dashboard.py` | Operator console and local web UI |

### Agent tools (exposed through the existing AgentLayer wallet MCP server)

`treasury_my_budget`, `treasury_request_payment`, `treasury_payment_status`, `treasury_simulate_charge` (sandbox),
`treasury_record_x402`, `treasury_cancel_payment`. With `AGENTLAYER_AGENT_ID` set, a host session is bound to one
agent and cannot read or spend another agent's budget.

### Payment states

`pending_approval → approved → card_issued | x402_ready → settled`, with `denied`, `expired` (card unused
past `active_to`; reservation released and card closed by `treasury sync`) and `cancelled` (card closed).
A card's `request_id` is the payment id, so a retried issuance cannot create a second card.

## Run it (≈5 minutes)

Requirements: macOS (for the Keychain-backed CardVault), Python 3.10+, an Airwallex **sandbox** account with Issuing
enabled. All amounts are sandbox money.

```bash
git clone <this repo> && cd <repo>
python3 -m venv agent-wallet/.runtime-venv
agent-wallet/.runtime-venv/bin/pip install -r agent-wallet/requirements.txt

# Sandbox credentials (Airwallex web app → Developer → API keys)
export AIRWALLEX_CLIENT_ID=...  AIRWALLEX_API_KEY=...

# Full scripted scenario: budgets, auto-approved card, rail declines, approval, deny,
# pause/freeze, x402 vs card routing, reconciliation, idle funds
./scripts/airwallex-demo.sh

# Operator UI
agent-wallet/scripts/treasury dashboard          # http://127.0.0.1:8787
```

Operator CLI:

```bash
T=agent-wallet/scripts/treasury
$T connect                                     # saves credentials (0600) under ~/.openclaw/agent-treasury
$T agent research-bot --budget 200 --per-tx 50 --auto 25 --mcc 5734 7372 5817
$T status                                      # budget / spent / reserved / available per agent
$T approvals ;  $T approve <id> ;  $T deny <id>
$T pause ops-bot                               # pause agent + freeze its live cards at Airwallex
$T payments ;  $T events ;  $T sync ;  $T idle ;  $T balances
$T request research-bot --merchant X --amount 19.99 --purpose "..." [--url https://merchant] [--mcc 5734]
$T charge <id> [--amount 24] [--mcc 7995]      # sandbox: merchant runs the authorization
```

Agents: add the wallet MCP server to Claude Code, Codex or Cursor (see `claude-code/plugins/agent-wallet`) and point it
at this package with `AGENT_WALLET_PACKAGE_ROOT=<repo>/agent-wallet`. The agent then sees the `treasury_*` tools next
to the wallet's x402, swap, vault and `use_saved_card` tools.

Tests: `PYTHONPATH=agent-wallet python agent-wallet/tests/smoke_airwallex_treasury.py` (offline: policy, ledger,
routing, adapter exposure, agent binding).

## Airwallex APIs used

`POST /authentication/login` · `GET /balances/current` · `GET /account` · `GET|POST /issuing/cardholders[/create]` ·
`POST /issuing/cards/create` · `GET /issuing/cards/{id}` · `GET /issuing/cards/{id}/details` ·
`GET /issuing/cards/{id}/limits` · `POST /issuing/cards/{id}/update` · `GET /issuing/transactions` ·
`POST /simulation/issuing/create` (sandbox). The Airwallex developer MCP was used during development for docs and
payload shapes.

## Sandbox vs production

- Merchant charges are simulated with `simulation/issuing/create`. In production, the merchant's real authorization
  hits the same card controls, and the agent pays through `use_saved_card` from the vault.
- The agent identity is a host-bound id (`AGENTLAYER_AGENT_ID`), the same trust model as Airwallex's agent-cards
  demo. Production needs a per-agent credential.
- Simulated sandbox transactions may stay `PENDING`; settlement in the ledger comes from the authorization result
  and `treasury sync`.
- Remote authorization (Airwallex calling our policy in real time) would move `decide()` onto the authorization
  path. That is the natural next step.
