# AgentLayer Wallet Hermes Plugin

This is a thin Hermes Agent bridge to the existing AgentLayer/OpenClaw wallet backend.

It intentionally does not copy the OpenClaw TypeScript extension or reimplement wallet policy. Hermes gets three tools:

- `agent_wallet_tools` - lists the underlying wallet tools and schemas from the Python adapter without creating or unlocking a wallet.
- `agent_wallet_invoke` - forwards one tool call to `python -m agent_wallet.openclaw_cli invoke`.
- `agent_wallet_approve` - issues a short-lived approval token through `python -m agent_wallet.openclaw_cli issue-approval` after explicit user confirmation of the exact preview summary.

OpenClaw remains the primary local environment. This plugin only expands the same backend into Hermes.

## Integration Plan

1. Keep wallet behavior and safety policy in `agent-wallet/`.
2. Keep OpenClaw as the primary environment and leave `.openclaw/extensions/agent-wallet` unchanged.
3. Register a small Hermes bridge instead of one Hermes tool per wallet operation.
4. Use discovery from `OpenClawWalletAdapter.list_tools()` so Hermes sees the current backend schemas without duplicated metadata.
5. Forward execution to `agent_wallet.openclaw_cli invoke` so config validation, sealed secrets, approval-token checks, and backend dispatch stay authoritative in Python.
6. Forward token issuance to `agent_wallet.openclaw_cli issue-approval` so Hermes can complete preview/approve/execute without learning sealed secrets.
7. Cache successful Solana swap previews briefly in Hermes and bind the cached payload digest into the approval token. Execute can then reuse the exact Jupiter preview the user approved instead of re-quoting volatile markets.
8. Add broader Hermes ergonomics later only where it improves safety, such as an installer wrapper or read-only status command.

## Install

Copy or symlink this directory into a Hermes plugin path:

```bash
mkdir -p ~/.hermes/plugins
ln -s /absolute/path/to/openclaw_skill/hermes/plugins/agent_wallet ~/.hermes/plugins/agent_wallet
```

Set the wallet package root if Hermes is not launched from this repository:

```bash
export AGENT_WALLET_PACKAGE_ROOT=/absolute/path/to/openclaw_skill/agent-wallet
export AGENT_WALLET_PYTHON=python3
```

Then enable or reload plugins in Hermes:

```bash
hermes plugins
hermes chat
```

## Runtime Notes

- Secrets must stay in the existing protected runtime path, especially `~/.openclaw/sealed_keys.json`.
- Do not pass `privateKey`, `masterKey`, or `approvalSecret` through Hermes tool config.
- Write-capable wallet tools still require preview first and an `approval_token` bound to the exact `confirmation_summary`.
- Use `agent_wallet_approve` only after the user explicitly confirms the exact operation. Mainnet execute requires `mainnet_confirmed=true`.
- Use `agent_wallet_tools` before invoking unfamiliar tool names.
- Solana swap previews are cached at `~/.hermes/agent_wallet_preview_cache.json` with `0600` permissions for a short window. The cache contains unsigned preview payloads only; signing and approval checks remain in `agent-wallet/`.
