# Agent Wallet Codex Plugin

This plugin adds the existing local AgentLayer wallet runtime to Codex.

It does not create a new wallet. It reuses the current runtime under:

```bash
~/.openclaw/agent-wallet-runtime/current/agent-wallet
```

Primary design rules:

- keep wallet policy, approvals, and signing in `agent-wallet/`
- keep this plugin as a thin MCP bridge for Codex
- reuse the same wallets, networks, and tool surface already used by OpenClaw and Hermes
- avoid secrets in plugin config or marketplace metadata

## What it exposes

- direct wallet tools for Solana and EVM
- session wallet selection with `set_wallet_backend`
- EVM network selection with `set_evm_network`
- auto-managed approval binding for `preview -> execute` write flows
- bundled Codex skills, including `wallet-sol` for showing the Solana wallet
  portfolio directly in chat, `wallet-base` for showing the Base EVM
  wallet portfolio and switching the session's active backend to Base,
  `cards` for issuing a Laso Finance prepaid card paid via x402, and `x402`
  for discovering and paying arbitrary x402 services via CDP Bazaar or
  Agentic Market

## MCP tool approvals

The bridge publishes the backend's `read_only` classification as MCP
`readOnlyHint` and `destructiveHint` annotations. Balance reads, active-wallet
inspection, service discovery and x402 previews are advertised as reads.
Payments and other writes remain potentially destructive; tools without an
explicit read-only classification are treated as writes.

These hints help Codex classify calls, but do not override its MCP approval
settings. A host that requires approval while its session disallows approval
prompts can still reject a call before it reaches this bridge. After updating
the plugin, restart the host to reload tool metadata. Wallet payment approval
tokens and execution checks are independent and still apply.

See the [Codex configuration reference](https://learn.chatgpt.com/docs/config-file/config-reference)
for per-server and per-tool approval settings.

## Question menus in Codex

Like Claude's explicit `AskUserQuestion` calls, Codex skills call the native
`functions.request_user_input_async` at the relevant choice/confirmation step.
The payload uses `questions[].title` and string `options`; it is not a wallet
MCP tool and is not configured through Claude's `allowed-tools` metadata.
Claude's `mcp__plugin_wallet_agent-wallet__*` aliases are not copied: resolve
wallet tool names against the active Codex MCP surface (for example,
`mcp__agent_wallet__swap_evm_tokens`). The short names in skills refer to those
existing wallet tools, not new wrapper commands.
`wallet-operator` also covers plain-language swaps, transfers and other wallet
writes: render a compact transaction-preview table in chat before opening the
confirmation menu. Swap tables normally have four rows (spend, estimated receive,
slippage, gas); disclose exceptional fees or material warnings below instead of
adding routine allowance, self-recipient, zero-fee or pending-simulation rows. Existing consent and backend approvals still apply;
chat is the fallback when the async tool is absent or disallows the purpose.
After an async question is accepted, skills keep the turn open using native
wake-on-input `clock.sleep` calls, without a final answer until the user replies.
Hosts without both tools use chat fallback. Host-mandated explanations and
skill citations remain controlled by the host.

## Runtime requirements

- The primary route is `npx @agentlayer.tech/wallet install --yes`.
- The alternative Git marketplace route is:

  ```bash
  codex plugin marketplace add lopushok9/Agent-Layer
  codex plugin add agent-wallet@agentlayer
  ```

  The marketplace plugin installs the shared runtime through the npm package
  on first MCP start if it is missing. Node.js 24, npm, and Python 3 are
  required. Restart ChatGPT desktop or Codex after installation.
- keep the local wallet files and `~/.openclaw/sealed_keys.json` in place
- `wallet codex install --yes` remains available for the npm-managed local
  plugin path

## Bundled skills

After either installation route and a host restart, the plugin ships bundled
skills:

- `wallet-sol` — invoke from the slash menu or explicitly as `$wallet-sol`
  to render the connected Solana wallet portfolio as a compact chat table.
- `wallet-base` — invoke from the slash menu or explicitly as `$wallet-base`
  to render the connected Base EVM wallet portfolio as a compact chat table
  and switch the session's active wallet backend to Base.
- `cards` -- invoke from the slash menu or explicitly as `$cards` to issue a
  Laso Finance prepaid card (US or international), paid via x402 from the
  connected wallet.
- `x402` -- invoke from the slash menu or explicitly as `$x402` to discover
  x402-paid services via CDP Bazaar or Agentic Market (or use a URL already
  given), preview the payment terms, and pay from the connected wallet.
- `yield` -- invoke from the slash menu or explicitly as `$yield` to scan the
  wallet's Morpho vault positions on Base and Ethereum for better-yielding
  vaults with the same asset, set the scan up as a Codex automation every 3
  days, or move a position after an explicit confirmation.

## Path resolution

The bridge resolves the wallet runtime from:

1. `AGENT_WALLET_PACKAGE_ROOT`
2. `OPENCLAW_AGENT_WALLET_PACKAGE_ROOT`
3. `~/.openclaw/agent-wallet-runtime/current/agent-wallet`

If the runtime lives elsewhere, set one of the env overrides before starting Codex.

## Saved card catalog

`list_saved_cards` returns this runtime user's references and masked metadata.
`get_saved_card_status` refreshes pending issuance when due by default;
`refresh=false` is a cached read. `refresh_saved_card` performs the same free,
rate-limited retrieval explicitly. No owner unlock, signing or payment is needed.
Outputs never contain PAN, CVV or provider tokens. Once issuance is complete,
working credentials are retired and statuses/balances remain cached snapshots.
These tools are advertised as reads: issuer retrieval may update local encrypted
cache files but never places orders or moves funds. Host MCP approval settings
still apply. Full reveal remains an owner CLI operation with macOS authentication.

### Private card use

`use_saved_card` previews an exact HTTPS request with card-field placeholders
and can combine Laso issuance and use under one normal host confirmation.
Execute with its `operation_id`. `continue_vault_operation` resumes an already
authorized delayed task without a second approval or owner unlock;
`get_vault_operation` reads its cached state. The fixed executor substitutes
fields internally and returns HTTP status only. It never exposes PAN/CVV or
raw provider output and never automatically repeats an uncertain payment.

Runtime-encrypted `.use` card capsules enable this path without a Keychain
prompt per use. They are decryptable by the wallet runtime, including after
issuance; this is a different boundary from the owner-authenticated reveal CLI.
Authorization lasts 48 hours and binds the exact request/card/wallet. This
supports private HTTPS use and managed Kernel checkout; local Chrome autofill remains separate.

### Kernel browser connection

Run `wallet vault kernel-connect` in your own terminal and paste the dashboard
API key at the hidden prompt. The key is saved in the encrypted runtime bundle,
never in plugin config or chat. `wallet vault kernel-status` reports configuration;
`wallet vault kernel-disconnect` removes the saved key.

`kernel_browser` prepares a billable cloud checkout with public form data.
`use_saved_card(checkout=...)` binds the browser, exact page, USD total, field
selectors and submit action to the existing host confirmation. It can issue a
card in that same task. The backend fills privately, locks observations and
closes the session after one attempt. Kernel and the merchant process the real
card data; the model receives only safe status. No local browser installation
is needed. See [the vault guide](../../../agent-wallet/CARD_VAULT.md) for limits and cleanup behavior.
