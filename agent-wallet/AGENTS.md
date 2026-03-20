# AGENTS.md

## Scope
These instructions apply to the entire `agent-wallet/` tree.

## Purpose
`agent-wallet` is the Python wallet backend used by OpenClaw. It owns:

- wallet runtime configuration
- per-user wallet provisioning
- Solana read/write operations
- approval-token validation for sensitive execution
- OpenClaw-facing adapter and CLI bridge
- local installer and config patching scripts

## Architecture map

### Main entrypoints
- `agent_wallet/openclaw_cli.py` — JSON CLI bridge invoked by the TypeScript OpenClaw extension.
- `agent_wallet/openclaw_runtime.py` — assembles a runtime context for one OpenClaw user session.
- `agent_wallet/openclaw_adapter.py` — exposes backend operations as safe agent-facing tools and enforces preview/prepare/execute policy.
- `agent_wallet/plugin_bundle.py` — builds the manifest/tool bundle exposed to hosts.

### Configuration and secrets
- `agent_wallet/config.py` — central place for runtime settings, RPC resolution, boot key resolution, and sealed secret loading.
- `agent_wallet/sealed_keys.py` — encrypted secret bundle support for `~/.openclaw/sealed_keys.json`.
- `agent_wallet/encrypted_storage.py` — encrypted wallet file helpers.

### Wallet backend
- `agent_wallet/wallet_layer/factory.py` — constructs the configured backend.
- `agent_wallet/wallet_layer/solana.py` — main Solana backend implementation.
- `agent_wallet/providers/solana_rpc.py` — Solana RPC access.
- `agent_wallet/providers/jupiter.py` — Jupiter API integration.

### User wallet lifecycle
- `agent_wallet/user_wallets.py` — per-user wallet paths, creation, loading, and migration behavior.
- `agent_wallet/bootstrap.py` — wallet bootstrap helpers and address pinning.

### Transaction safety
- `agent_wallet/approval.py` — host-issued approval tokens.
- `agent_wallet/nonce_registry.py` — single-use token replay protection.
- `agent_wallet/transaction_policy.py` — policy validation around transaction execution.
- `agent_wallet/spending_limits.py` — spending guardrails.

### Scripts
- `scripts/install_agent_wallet.py` — local installer for Python env + OpenClaw config setup.
- `scripts/install_openclaw_local_config.py` — writes plugin config into OpenClaw config.
- `scripts/install_openclaw_sealed_keys.py` — provisions sealed runtime secrets.
- `scripts/switch_openclaw_wallet_network.py` — helper for switching the configured Solana network.

## Working rules

### Keep responsibilities separated
- Keep host bridge logic in `openclaw_cli.py` and `openclaw_runtime.py`.
- Keep agent-facing safety and tool exposure in `openclaw_adapter.py`.
- Keep chain-specific behavior in `wallet_layer/solana.py` and provider modules.
- Keep config precedence in `config.py`; do not duplicate env resolution elsewhere unless necessary.

### Security invariants
- Do not add runtime support for loading `AGENT_WALLET_MASTER_KEY`, `AGENT_WALLET_APPROVAL_SECRET`, or `SOLANA_AGENT_PRIVATE_KEY` directly from runtime env again.
- Do not put secrets into plugin config JSON.
- Preserve the `preview -> prepare -> execute` flow for write operations.
- `prepare` must never return signed transaction bytes.
- `execute` must continue requiring a host-issued `approval_token`.
- On `mainnet`, preserve explicit confirmation requirements and warnings.

### Update discipline
- Prefer fixing behavior in the Python backend instead of patching around it in scripts.
- When adding or removing a tool, keep the following in sync:
  - `agent_wallet/openclaw_adapter.py`
  - `agent_wallet/plugin_bundle.py`
  - OpenClaw extension tool registration in `.openclaw/extensions/agent-wallet/index.ts`
  - relevant docs/tests
- When changing config keys, keep the following in sync:
  - `agent_wallet/config.py`
  - `agent_wallet/openclaw_cli.py`
  - `.openclaw/extensions/agent-wallet/openclaw.plugin.json`
  - installer scripts and README examples

### Coding style
- Follow existing Python style and type-hint usage.
- Keep changes minimal and local to the owning module.
- Avoid introducing framework-heavy abstractions; this repo is intentionally direct.
- Prefer explicit JSON-serializable return payloads because the CLI bridge depends on them.

## Validation
- Prefer targeted smoke tests first, then broader runs if needed.
- Relevant tests live under `tests/` and are mostly smoke-style.
- Good focused examples:
  - `tests/smoke_openclaw_cli.py`
  - `tests/smoke_openclaw_adapter.py`
  - `tests/smoke_openclaw_runtime.py`
  - `tests/smoke_install_agent_wallet.py`
  - `tests/smoke_sealed_keys.py`
  - `tests/smoke_solana_tx.py`

## Common change patterns

### If changing tool behavior
1. Update backend or adapter.
2. Verify preview/prepare/execute semantics.
3. Sync tool metadata exposed to OpenClaw.
4. Update or add smoke tests.

### If changing config or install flow
1. Update `config.py` and any CLI/env mapping.
2. Update installer scripts.
3. Update README snippets and examples.
4. Run install/config smoke tests.

### If changing Solana execution logic
1. Keep address validation and policy checks intact.
2. Preserve sign-only behavior.
3. Preserve exact confirmation summaries used for approval tokens.
4. Re-run the most specific Solana smoke tests available.
