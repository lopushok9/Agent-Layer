# Changelog

## Unreleased

## v0.1.16 - 2026-05-16

- Added Flash Trade perpetuals support to the Solana wallet flow, including
  market discovery, position lookup, preview, prepare, open, and close tools.
- Kept Flash perps wallet-native inside the existing Solana backend instead of
  introducing a separate custodial trading account flow.
- Added a repo-owned Flash SDK bridge for real quote, prepare, and execution
  planning against Flash Trade from the local runtime.
- Fixed OpenClaw runtime packaging and plugin contract sync so Flash Trade
  tools are exposed correctly from the installed runtime.
- Bound Flash execute approvals to the exact approved preview payload, so
  host-issued approvals remain valid across small quote drift between preview
  and execution.

- Added ClawHub-publishable OpenClaw plugin package metadata for
  `.openclaw/extensions/agent-wallet` and `.openclaw/extensions/pay-bridge`,
  including required `openclaw.compat`, `openclaw.build`, and
  `runtimeExtensions` fields for native `openclaw plugins install clawhub:...`
  installs.
- Added a reproducible OpenClaw plugin package build/check script at
  `scripts/manage_openclaw_plugin_packages.mjs` to generate published runtime
  JS artifacts under `.openclaw/extensions/*/dist/`.
- Updated the `agent-wallet` OpenClaw bridge to auto-check the packaged runtime
  path at `~/.openclaw/agent-wallet-runtime/current/agent-wallet` before local
  workspace fallbacks, so a ClawHub-installed plugin can ride on top of the
  existing npm runtime installer.
- Documented the dual-install model: keep `npx @agentlayer.tech/wallet install`
  for runtime/bootstrap, and use `openclaw plugins install clawhub:...` for the
  native OpenClaw plugin packages.
- Added a GitHub Actions workflow at `.github/workflows/clawhub-plugins.yml`
  that can dry-run ClawHub publishes on pull requests and publish both OpenClaw
  plugin packages on `v*` tags or manual dispatch.

## v0.1.14 - 2026-05-13

- Added a separate `.openclaw/extensions/pay-bridge/` plugin that keeps
  `pay.sh` API payments outside the main AgentLayer execution wallet stack.
- Added OpenClaw tools for local `pay` discovery and execution:
  `pay_status`, `pay_wallet_info`, `pay_search_services`,
  `pay_get_service_endpoints`, and `pay_api_request`.
- Updated the local OpenClaw installer/runtime config flow to package and
  enable the `pay-bridge` plugin alongside `agent-wallet`, including its
  tool allowlist and absolute `pay` binary path when available.
- Added an optional Hermes Agent bridge plugin under `hermes/plugins/agent_wallet`
  that forwards into the existing Python wallet CLI instead of duplicating
  OpenClaw wallet tools or policy.
- Added `wallet hermes install --yes` and `AGENT_WALLET_BOOT_KEY_FILE` support
  for smoother Hermes onboarding without manual `.env` editing.
- Added Hermes EVM onboarding helpers:
  `agent_wallet_evm_status` and `agent_wallet_evm_setup`.
- Added host-side EVM bootstrap scripts for packaged/runtime installs:
  `manage_openclaw_evm_wallet.py`, `bootstrap_openclaw_evm.py`, and
  `setup_evm_wallet.sh`.
- Kept Hermes EVM routing on the existing `wdk-evm-wallet` and
  `provider-gateway` path for `ethereum` and `base`, without copying wallet
  policy or duplicating tool implementations.
- Replaced the repo license with `PolyForm Small Business 1.0.0`.
- Clarified in `README.md` that individuals can audit, fork, run, and modify
  the code for themselves, and that company use follows the PolyForm small
  business limits.
- Removed direct Mayan swap routing from `agent-wallet`, `.openclaw`, and
  `wdk-evm-wallet`; cross-chain swaps now stay on LI.FI/Jupiter-backed paths
  with Mayan denied as a LI.FI bridge.

## v0.1.12 - 2026-05-06

### Added

- Hermes EVM runtime helpers for packaged installs:
  `agent_wallet_evm_status` and `agent_wallet_evm_setup`.
- Host-side EVM lifecycle scripts in the runtime bundle:
  `manage_openclaw_evm_wallet.py`, `bootstrap_openclaw_evm.py`, and
  `setup_evm_wallet.sh`.

### Changed

- Hermes installs now support the same local EVM onboarding shape as BTC:
  inspect runtime health, auto-start the local service, create or unlock the
  vault wallet, and bind paired `ethereum/base` networks through the thin
  bridge.

## v0.1.0-beta.2 - 2026-03-31

Second public beta release that expands the stack beyond the initial MCP, wallet, and AgentLayer bridge scope.

### Added

- `wdk-btc-wallet/`: separate BTC-only wallet service built on top of Tether WDK for local Bitcoin wallet operations.
- `provider-gateway/`: non-custodial shared provider access layer for hosted Solana RPC defaults, Bags launch and fees, and Jupiter Earn.
- `docs/`: Starlight-based documentation app for AgentLayer onboarding, architecture, and capability docs.

### Notes

- `mcp-server/`, `agent-wallet/`, and `.openclaw/extensions/agent-wallet/` remain part of the beta stack from `v0.1.0-beta.1`.
- This is still a beta release intended for testing, onboarding, and early integration work.
- Mainnet use should remain explicit, operator-approved, and cautious.

## v0.1.0-beta.1 - 2026-03-21

First public beta centered on the repo's three primary deliverables: `mcp-server`, `agent-wallet`, and the AgentLayer bridge in `.openclaw/extensions/agent-wallet`.

### Added

- `mcp-server/`: finance and crypto MCP server with market, DeFi, on-chain, and agent identity tooling.
- `agent-wallet/`: Python wallet backend for local Solana wallet operations with guarded read, preview, prepare, and execute flows.
- `.openclaw/extensions/agent-wallet/`: repo-shipped AgentLayer extension bridge that forwards tool execution into the Python wallet backend.

### Notes

- This is a beta release intended for testing and early integration work.
- Mainnet use should remain explicit, operator-approved, and cautious.
