# Changelog

## Unreleased

## v0.1.33 - 2026-06-01

- Hardened runtime resolution end-to-end so a broken or stale runtime can no
  longer surface as an opaque MCP `-32000`.
  - `run_mcp.sh` (Codex + Claude Code) now self-checks the resolved `server.py`
    with `py_compile` and emits a structured, actionable JSON error (with a
    `fix` command) when the server is missing or fails to parse, instead of
    silently handing a broken file to Python. JSON errors are emitted safely so
    arbitrary paths cannot produce invalid JSON.
  - `doctor` / `doctor --deep` now validate the live `current` runtime — symlink
    integrity, venv python, `server.py` parse, a real MCP `initialize` handshake
    (under `--deep`), and per-editor resolution — and attach a `fix` command to
    every failing check (output is a structured `checks[]` array).
  - `install` / `update` now verify the newly-activated release via an MCP
    handshake and auto-rollback `current → previous` on failure, with guidance
    classified as `broken_release` (our side — you stay safe on the previous
    version) vs `local_env` (fixable locally). A first install with no previous
    version leaves no broken runtime active and does not park the broken release
    under `previous`.
  - `codex install` / `claude-code install` pin the resolved `OPENCLAW_HOME`
    into the editor `.mcp.json` env (bundle and, for Claude Code, existing
    version-keyed cache copies), eliminating launcher/installer home divergence.
    The venv python is intentionally not pinned so it stays correct across
    runtime upgrades.

## v0.1.32 - 2026-06-01

- Fixed a `SyntaxError` in `codex/plugins/agent-wallet/server.py` introduced by
  the Houdini private-swap removal in v0.1.31: the deletion left the orphaned
  `_cache_pending_private_swap_order` signature fused onto the body of
  `_normalize_wallet_backend`, leaving an unclosed parenthesis. The Codex and
  Claude Code plugins share this `server.py`, so the broken file prevented the
  agent-wallet MCP server from starting in both runtimes (JSON-RPC `-32000` /
  "failed to reconnect"). Restored the `_normalize_wallet_backend` definition;
  the server now starts and completes the MCP `initialize` handshake.
- Fixed Claude Code agent-wallet MCP failing to start (`-32000` / "failed to
  reconnect"). When Claude Code copies the plugin into its plugin cache, the
  launcher's relative `../../codex/...` and local `server.py` paths no longer
  resolve, so it reported "server.py not found". `run_mcp.sh` now falls back to
  the codex `server.py` inside the installed runtime package
  (`~/.openclaw/agent-wallet-runtime/current/codex/plugins/agent-wallet`), which
  is always present after install. Codex was unaffected (its launcher is
  self-contained).

## v0.1.31 - 2026-05-31

- Hardened the WDK EVM/BTC local vaults with a decrypt-on-demand key model: the
  decrypted seed is no longer held in process memory between requests. Each
  signing request decrypts the seed just-in-time from the sealed password and
  zeroizes the key/plaintext buffers afterward; `unlock`/`lock` are now
  deprecated no-ops. The at-rest format is unchanged, so existing wallets keep
  working without migration.
- EVM wallets are now provisioned automatically at install, alongside Solana.
  Every install creates both wallets; `--backend` only selects the active one.
  EVM provisioning auto-generates and seals the vault password and binds both
  base and ethereum. It is best-effort: an install-time failure does not abort
  the install, and the wallet is created lazily on first EVM use instead.
- Fixed the local config installer to validate EVM networks with the EVM
  normalizer (previously an EVM backend was rejected as a Solana network).

## v0.1.30 - 2026-05-30

- Added a Claude Code plugin bridge under `claude-code/plugins/agent-wallet` so
  the existing local wallet runtime can be used directly inside Claude Code
  without creating a new wallet.
- The Claude Code bridge connects to the current `~/.openclaw` runtime and
  reuses the same Solana, Bitcoin, and EVM wallet surface already used by
  OpenClaw, Hermes, and Codex.
- Added `wallet claude-code install --yes`, which symlinks the bundled Claude
  Code plugin into `~/.claude/plugins/agent-wallet` and attempts to register it
  via the Claude Code CLI.
- Fixed the `smoke_install_from_github` test, which was failing because
  `setup.sh` checks for the Codex plugin manifest but the test bundle never
  created that path.
- Added the Claude Code plugin manifest check to `setup.sh` so bundle integrity
  is validated for both the Codex and Claude Code plugin surfaces.

## v0.1.29 - 2026-05-29

- Added a new `Codex` plugin bridge under `codex/plugins/agent-wallet` so the
  existing local wallet runtime can be used directly inside Codex without
  creating a second wallet.
- Kept the Codex bridge non-custodial and additive: it reuses the current
  `agent-wallet` runtime, existing wallets, and the current tool surface
  instead of replacing OpenClaw or Hermes.
- Added `wallet codex install --yes`, which links the bundled Codex plugin into
  the standard local plugin marketplace path and can ask Codex to install the
  plugin from that local marketplace.
- Added `get_kamino_open_positions`, which aggregates the wallet's Kamino
  positions across markets with loan details, reserve APYs, and rewards.
- Removed Solana devnet/testnet support from the wallet runtime, host bridges,
  and local helper scripts so the supported Solana surface is now mainnet-only.
- Removed EVM testnet support from the wallet runtime and host bridges so the
  supported EVM surface is now `ethereum` and `base` mainnet only.
- Removed Bitcoin `testnet` and `regtest` support from the wallet runtime,
  host bridges, and local helper scripts so the supported BTC surface is now
  `bitcoin` mainnet only.

## v0.1.28 - 2026-05-28

- Simplified `x402_pay_request` into a single-shot paid execution flow while
  keeping `x402_preview_request` as an optional research tool.
- Hardened x402 execution with explicit payment requirement validation, longer
  paid-request timeouts, structured settlement logging, and safer settlement
  header parsing.
- Fixed Base x402 EVM signing by normalizing typed-data byte fields before
  sending them through the local WDK signer bridge.
- Reduced x402 preview confusion in OpenClaw by exposing a payment summary
  without approval-token style confirmation semantics.
- Added an early safety guard for `x402.alchemy.com` so unsupported wallet-auth
  flows fail before spending funds.

## v0.1.27 - 2026-05-27

- Improved Solana swap fallback landing by enabling Jupiter dynamic slippage
  and bounded `veryHigh` priority fees on the Metis `/swap` fallback path.
- Hardened Kamino transaction execution with local simulation before send,
  Kamino-specific build timeouts, and longer confirmation polling on mainnet.
- Reused approved Kamino preview payloads during execute so OpenClaw no longer
  needs to rebuild the same write path just to satisfy approval binding.
- Added Kamino obligation pinning for `withdraw`, `borrow`, and `repay`, so
  preview can require an explicit `obligation_address` and execute verifies the
  built transaction references the selected obligation before signing.

## v0.1.26 - 2026-05-26

- Reworked Solana Jupiter swaps to prefer intent approvals, so OpenClaw confirms
  risk limits and executes against a fresh quote instead of binding approval to
  a fragile exact quote payload.
- Added Jupiter Swap API V2 `/order` + `/execute` routing with managed landing
  support and fallback routing for Solana swaps.
- Hardened Solana swap intent defaults to 3% slippage, a 120-second execution
  window, three fresh execution attempts, and safer minimum-output handling.
- Fixed Jupiter V2 execution payload compatibility by sending
  `lastValidBlockHeight` in the string form expected by the API.
- Disabled legacy exact-preview Solana swap execute in the OpenClaw bridge to
  prevent stale approval-token mismatches on active markets.

## v0.1.24 - 2026-05-23

- Fixed the published npm package CLI metadata so
  `npx @agentlayer.tech/wallet install --yes` resolves the wallet installer
  command correctly.
- Updated the root README install guidance to describe the new local Solana
  mainnet wallet onboarding flow instead of requiring manual runtime secret
  exports.

## v0.1.23 - 2026-05-23

- Made the default Solana install flow mainnet-first for fresh local
  onboarding.
- Added host-side Solana wallet provisioning to the installer so
  `wallet install --yes` creates an encrypted per-user mainnet wallet when no
  explicit signer is already configured.
- Kept wallet secrets local by running runtime onboarding without
  provisioning-only secret environment variables and returning only public
  wallet metadata in installer output.
- Updated installer smoke coverage to verify encrypted wallet creation,
  mainnet config, address pinning, and absence of boot/master/approval secrets
  in stdout.

## v0.1.18 - 2026-05-19

- Started the native x402 buyer integration inside `agent-wallet` instead of
  the separate `pay-bridge` wallet path.
- Added read-only x402 discovery helpers for `CDP Bazaar` and
  `Agentic Market`, including normalized service/resource search results.
- Added `x402_preview_request`, which performs an unpaid request, parses
  `PAYMENT-REQUIRED`, and summarizes accepted payment options without spending
  funds.
- Added `x402_pay_request` with `prepare` and `execute` flow for exact buyer
  payments from the native wallet on Solana, Base, and Base Sepolia.
- Added buyer-side x402 signing support to the local EVM runtime so Base
  payments execute without requiring a separate wallet product.
- Fixed x402 Solana execution against hosted RPC routing by deriving an
  SDK-compatible direct Solana RPC URL for the x402 SVM client.
- Fixed x402 payment requirement selection so SDK model objects survive through
  prepare and execute without crashing on plain dict access.
- Added automatic host approval-token issuance for `x402_pay_request` from the
  cached `x402_preview_request` summary in the OpenClaw bridge.
- Fixed x402 approval-token binding so execute validates against the exact
  `confirmation_summary` used by the Python wallet policy gate.
- Synced the OpenClaw coding profile allowlist and runtime bundle so the new
  x402 tools are exposed correctly in packaged installs.

## v0.1.17 - 2026-05-17

- Added Flash Trade collateral-aware perp opens so the Solana wallet flow can
  use the collateral supported by the selected Flash market instead of forcing
  `collateral_symbol == market_symbol`.
- Unblocked docs-aligned short-position previews, prepares, and execution for
  markets such as `SOL short / USDC collateral`.
- Tightened Flash market selection to match on `market_symbol + side +
  collateral_symbol`, preventing incorrect market resolution when the same
  asset has multiple collateral paths.
- Updated the OpenClaw tool descriptions and Flash SDK bridge docs to reflect
  supported Flash collateral paths instead of the earlier same-symbol-only
  limitation.

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
