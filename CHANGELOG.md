# Changelog

## Unreleased

- Replaced automatic editor reinstallation after every runtime update with a
  narrow migration of stale runtime-owned symlinks and Hermes env paths. Codex
  and Claude MCP source manifests are now immutable; only user-owned Claude
  cache copies may receive a custom `OPENCLAW_HOME` pin. The versioned runtime
  now includes the previously omitted `claude-code/` bridge.

- Staged normal installs under hidden `releases/.staging-*` directories and
  verify them before switching `current`. Failed candidates are moved to
  `.failed-*`, excluded from `available_releases`, and recorded in an update
  journal; on failure, existing `current` and `previous` pointers remain untouched.

- Centralized installer boot-key selection in the active Python runtime. When
  sealed secrets exist, conflicting env, keystore, and legacy-file candidates
  are tested against `sealed_keys.json`; a stale higher-priority value can no
  longer mask the key that actually decrypts the bundle. Older runtimes retain
  the existing JavaScript fallback for upgrade compatibility.

- Removed a test-only `OPENCLAW_HOME` pin that leaked into the published Claude
  Code MCP manifest. Installer regression tests now isolate every editor home,
  assert that tracked plugin sources remain unchanged, and inspect the packed
  npm MCP manifests for temporary or user-specific absolute paths.

## v0.1.73 - 2026-07-09

- Fixed CLI installer/update boot-key precedence when recovering an existing
  hardened install. `buildInstallerEnv()` now resolves the boot key in the same
  order as the runtime itself: explicit env first, then keystore, and only then
  plaintext fallback files. This prevents a stale
  `~/.openclaw/agent-wallet-runtime/boot-key` from overriding a correct key in
  the keystore and breaking `wallet install` / `wallet update` even though the
  active runtime can still decrypt `sealed_keys.json`.
  - `bin/openclaw-agent-wallet.mjs`
  - `agent-wallet/tests/smoke_cli_install_prefers_keystore_over_stale_boot_file.py`

## v0.1.72 - 2026-07-09

- Fixed a `0.1.71` installer regression where `wallet update --yes` could fail
  during the nested OpenClaw config step on hardened installs with:
  `AGENT_WALLET_BOOT_KEY is required`. The config installer was checking only
  the direct env var even though the runtime now legitimately resolves the boot
  key via the OS keystore or `agent-wallet-runtime/boot-key`. It now uses the
  shared boot-key resolver, so update/install works again when the boot key is
  available through the supported non-env paths.
  - `agent-wallet/scripts/install_openclaw_local_config.py`
  - `agent-wallet/tests/smoke_install_openclaw_local_config_sealed.py`

## v0.1.71 - 2026-07-09

- Fixed `wallet update` leaving editor integrations pinned to a stale
  `releases/<version>` path after a runtime upgrade. The installer and
  OpenClaw local config now canonicalize runtime-owned paths back through
  `~/.openclaw/agent-wallet-runtime/current`, and the update command
  proactively refreshes existing Hermes, Codex, and Claude Code installs so a
  successful update rewires old integrations to the new active runtime
  automatically. The `update` CLI path also now returns its final update JSON
  payload directly instead of leaking the nested install payload shape.
  - `bin/openclaw-agent-wallet.mjs`
  - `agent-wallet/scripts/install_openclaw_local_config.py`
  - `agent-wallet/tests/smoke_install_openclaw_local_config_runtime_defaults.py`
  - `agent-wallet/tests/smoke_npm_installer.py`
  - `agent-wallet/tests/smoke_update_repairs_editor_installs.py`

- Fixed the EVM live tool list dropping the read-only `x402_*` service tools
  because the adapter returned before appending them. EVM-backed runtimes now
  expose x402 discovery/preview/pay tool specs consistently alongside the rest
  of the EVM wallet surface.
  - `agent-wallet/agent_wallet/openclaw_adapter.py`
  - `agent-wallet/tests/smoke_openclaw_evm_x402_tools.py`

- Fixed the npm `files` allowlist dropping `.env.example` for `wdk-evm-wallet`
  and `wdk-btc-wallet`. Both templates are tracked in git and correctly
  un-ignored (`!.env.example` in `.gitignore`), but the root `package.json`
  `files` list enumerated each wdk package's shipped files individually and
  omitted `.env.example` (unlike the `agent-wallet/.env.example` entry, which
  was listed correctly). On a machine with no pre-existing `.env`,
  `run-local.sh`'s self-heal (`cp .env.example .env`) failed under `set -eu`,
  and the Python bridge surfaced this as an opaque "wdk-evm-wallet exited
  before becoming healthy" with no indication that the template file itself
  was missing from the installed package.
  - `package.json`

- Fixed local EVM autostart incorrectly trusting any healthy same-version
  `wdk-evm-wallet` already listening on the shared localhost port. If a temp or
  alternate `OPENCLAW_HOME` had left a daemon running, host runtimes could hit
  `Unauthorized` because the daemon served a different `dataDir` and bearer
  token than the current install expected. Local EVM startup now also validates
  the reported `dataDir` from `/health` and restarts mismatched daemons before
  issuing authenticated requests.
  - `agent-wallet/agent_wallet/evm_user_wallets.py`
  - `agent-wallet/scripts/bootstrap_openclaw_evm.py`
  - `agent-wallet/tests/smoke_openclaw_evm_runtime_restart_wrong_home.py`

## v0.1.62 - 2026-07-04

- Made default boot-key storage prompt-free on macOS. The automatic keystore
  selection no longer probes macOS Keychain because even a read/probe through
  `/usr/bin/security` can open a GUI password dialog during install or session
  startup. macOS Keychain remains available only through explicit opt-in with
  `AGENT_WALLET_KEYSTORE_BACKEND=macos-keychain` (or `native`), while the
  default path uses the local fallback without showing Keychain prompts.
  - `agent-wallet/agent_wallet/keystore.py`
  - `agent-wallet/tests/smoke_keystore.py`

## v0.1.61 - 2026-07-04

- Hardened boot-key installation and migration around desktop keystores:
  - The npm installer provisions the boot key through the runtime Python
    keystore bridge instead of unconditionally persisting it in the release
    `.env`, while keeping a legacy `.env` fallback when no non-interactive
    keystore round-trip is available.
  - The Node keystore bridge is bounded by a timeout so a hung Python/keychain
    operation cannot stall install or reinstall.
  - macOS keychain writes now run with non-interactive stdin, convert timeouts
    into failed command results, and make the problematic
    `set-generic-password-partition-list` ACL update strictly best-effort.
  - Keystore resolution now verifies that a native backend can read the live
    boot key or complete a write/read/delete probe before selecting it, falling
    back cleanly when the OS tool exists but cannot authorize writes.
  - `agent-wallet/agent_wallet/keystore.py`
  - `bin/openclaw-agent-wallet.mjs`
  - `agent-wallet/tests/smoke_keystore.py`

## v0.1.58 - 2026-07-01

- Resolved SPL token symbol/name in `get_wallet_portfolio` via a batched,
  concurrent Jupiter token-search lookup, so `/wallet-sol` shows tickers
  (e.g. `USDC`) instead of raw mint addresses. The mint/token_address is
  still returned in full and rendered shortened next to the label rather
  than dropped. Falls back gracefully (symbol=None) when a mint isn't
  indexed or the lookup provider is unavailable.
  - `agent-wallet/agent_wallet/providers/jupiter.py`
  - `agent-wallet/agent_wallet/wallet_layer/solana.py`
  - `claude-code/plugins/agent-wallet/commands/wallet-sol.md`
  - `codex/plugins/agent-wallet/skills/wallet-sol/SKILL.md`
- Dropped the `/wallet-sol` source-metadata footer line (`source`,
  `token_discovery_source`, `pricing_source`, `pricing_errors`) from the
  rendered chat output for a more compact report.
  - `claude-code/plugins/agent-wallet/commands/wallet-sol.md`
  - `codex/plugins/agent-wallet/skills/wallet-sol/SKILL.md`

## v0.1.57 - 2026-07-01

- Added a bundled Codex `wallet-sol` skill so Codex users can render the
  connected Solana wallet portfolio in chat the same way Claude Code's
  `/wallet-sol` command does.
  - `codex/plugins/agent-wallet/skills/wallet-sol/SKILL.md`
  - `codex/plugins/agent-wallet/README.md`
- Fixed the resident read worker (used by `get_wallet_balance` /
  `get_wallet_portfolio`, e.g. `/wallet-sol`) decrypting the wallet's private
  key on every read-only cold start even though it never needed it. Read-only
  onboarding now resolves the address from the existing plaintext wallet pin
  file once a wallet has been provisioned, instead of unsealing secrets and
  deriving a signer just to discard it.
  - `agent-wallet/agent_wallet/user_wallets.py`
- Reduced `/wallet-sol` context payload by dropping the unused raw Jupiter
  price blob (`price_raw`) from portfolio token entries.
  - `agent-wallet/agent_wallet/wallet_layer/solana.py`
- Parallelized Jupiter price batch fetches in `get_portfolio` instead of
  awaiting each 20-mint batch sequentially, speeding up portfolio lookups for
  wallets with many SPL token accounts.
  - `agent-wallet/agent_wallet/wallet_layer/solana.py`
- Added a background prewarm of the resident read worker at MCP server
  startup so interpreter boot and onboarding overlap with the user issuing
  the first read-only command instead of blocking it. Opt out with
  `AGENT_WALLET_PREWARM_READ_WORKER=0`.
  - `codex/plugins/agent-wallet/server.py`
- Added idle eviction for resident read workers left over from a stale
  config (e.g. after switching Solana network or wallet backend), bounded by
  `AGENT_WALLET_READ_WORKER_IDLE_SECONDS` (default 10 minutes), and closed
  resident read workers on SIGTERM in addition to the existing `atexit`
  cleanup, since Python does not run `atexit` hooks on signal termination.
  - `codex/plugins/agent-wallet/server.py`

## v0.1.54 - 2026-06-29

- Fixed Claude Code autonomous-mode slash command activation so
  `/agentlayer-autonomous-approve` no longer relies on the model treating the
  slash invocation itself as sufficient consent. The command now uses an
  explicit in-command confirmation step before enabling the standing
  permission, and both autonomous toggle commands are marked manual-only in the
  Claude Code command metadata.
  - `claude-code/plugins/agent-wallet/commands/agentlayer-autonomous-approve.md`
  - `claude-code/plugins/agent-wallet/commands/agentlayer-autonomous-revoke.md`
  - `claude-code/plugins/agent-wallet/README.md`

## v0.1.53 - 2026-06-26

- Fixed Morpho vault and market quote (preview) requests timing out under the
  default 10 s HTTP budget. The Morpho SDK fetches vault state from
  `api.morpho.org/graphql` and runs on-chain simulation before returning a
  quote, which regularly exceeds 10 s. Added all six quote paths
  (`/v1/evm/morpho/vault/{supply,withdraw}/quote` and
  `/v1/evm/morpho/market/{supply_collateral,borrow,repay,withdraw_collateral}/quote`)
  to `LONG_RUNNING_POST_PATHS` so they share the 120 s budget already applied
  to the corresponding send paths.
  - `agent-wallet/agent_wallet/providers/wdk_evm_local.py`
- Extended the high-trust autonomous permission mode beyond Base swaps and made
  it a single combined permission group. `/agentlayer-autonomous-approve`
  enables both Base Velora/Uniswap swaps and supported EVM DeFi write tools
  (Aave, Morpho vault/market, and Lido staking/withdrawal) on Ethereum/Base;
  `/agentlayer-autonomous-revoke` disables both together. Covered execute calls
  use the same fresh-preview/internal-approval path while retaining exact
  summary and quote-fingerprint binding. Transfers, bridges, Solana swaps, and
  generic contract calls remain outside this standing permission.

## v0.1.47 - 2026-06-16

- Fixed Solana swaps of Token-2022 tokens with complex extensions (e.g. Backpack
  xStock tokens such as SPCX, which carry `scaledUiAmountConfig`,
  `pausableConfig`, `permanentDelegate`, and `confidentialTransferMint`) that
  consistently failed with "Provider swap transaction simulation failed". When a
  simulation failure is detected during `execute_swap_intent`, the next retry
  now passes `excludeDexes=GoonFi V2` to the Jupiter lite-api quote, forcing
  routing through a DEX that handles these extensions correctly (ZeroFi).
  - `providers/jupiter.py`: `fetch_quote`/`_fetch_quote_direct` accept an
    optional `exclude_dexes`, passed through as the `excludeDexes` query param.
  - `wallet_layer/solana.py`: `preview_swap` propagates `exclude_dexes` into the
    metis fallback; `execute_swap_intent` tracks a simulation-failure flag and
    excludes `GoonFi V2` on the retry. Default behavior is unchanged (no DEX
    exclusion unless a prior attempt failed simulation). (#14)
- First published release carrying the Morpho lending integration and the
  fresh-venv install hardening previously rolled out only locally (see the
  0.1.45 and 0.1.46 entries below).

## v0.1.46 - 2026-06-14

- Hardened the runtime install so a freshly created venv does not fail on
  native dependencies. The venv fingerprint hashes `pyproject.toml`, whose
  version line changes every release, so each bump builds a brand-new venv with
  the pip that `ensurepip` bundled. That pip could resolve `cryptography` and
  `ckzg` to versions without a prebuilt wheel and fall back to a source build
  needing a Rust/C toolchain, failing the install on machines that lack one.
  The installer now upgrades pip/setuptools/wheel in a new venv and runs the
  editable install with `--prefer-binary`, keeping native deps on prebuilt
  wheels.

## v0.1.45 - 2026-06-14

- Added a Morpho lending integration (vaults + Blue markets) on Ethereum and
  Base, exposed across all local agent frameworks (OpenClaw, Codex,
  Claude Code) through the shared agent-wallet adapter.
  - Read-only discovery: `get_evm_morpho_vaults`, `get_evm_morpho_markets`,
    and `get_evm_morpho_positions`, backed by the Morpho GraphQL API.
  - Write flows with preview/prepare/execute and quote-fingerprint binding:
    `manage_evm_morpho_vault_position` (supply/withdraw) and
    `manage_evm_morpho_market_position`
    (supply_collateral/borrow/repay/withdraw_collateral), including automatic
    approval/authorization requirement execution and rollback on failure.
- Fixed three Morpho defects found while hardening the integration:
  - Vault list discovery used a non-existent GraphQL filter type
    (`VaultV2Filters` -> `VaultV2sFilters`), so the default vault listing
    failed on every call.
  - Single vault/market lookups now return `found: false` for a missing target
    instead of a confusing `morpho_api_failed`. The Morpho API answers a
    missing entity as a `NOT_FOUND` GraphQL error with HTTP 200, which the
    previous code treated as a hard failure.
  - Execute no longer rejects checksummed vault/market targets: the approval
    binding lowercases the resolved target, so it is now compared
    case-insensitively against the requested address/id.
- Made Morpho discovery usable without paging through a default-ordered slice:
  - Vaults: filter by underlying asset and order by TVL/APY (default
    `TotalAssetsUsd` desc).
  - Markets: free-text `search` plus collateral/loan asset filters, ordered by
    supply/APY (default `SupplyAssetsUsd` desc).
  - `order_by` is validated case-insensitively against an allowlist, and the
    read-path `marketId` is validated as a 32-byte hex string.

## v0.1.44 - 2026-06-12

- Added anonymous, privacy-first adoption telemetry so wallet usage can be
  measured across hosts (Claude Code / Codex / Hermes / OpenClaw) without any
  PII.
  - The wallet emits one event per tool invocation through the shared
    `openclaw_cli invoke` chokepoint. Events carry only a random local install
    id, host, the registered tool name, backend family, plugin version, and a
    success flag — never addresses, balances, amounts, tx hashes, arguments, or
    secrets. Secret-touching commands (onboard/wallet-create/unlock/import) are
    never instrumented.
  - Delivery uses a durable local spool plus a detached best-effort flush to the
    provider-gateway, so a short-lived CLI process never adds latency or loses
    events.
  - Opt out at any time with `AGENT_WALLET_NO_TELEMETRY=1` (zero footprint).
  - Per-frontend `host` tagging via `AGENT_WALLET_HOST` in each bridge.

## v0.1.41 - 2026-06-07

- Hardened Uniswap Trading API swap execution on active EVM mainnet markets.
  - Stabilized the Uniswap quote fingerprint so `preview -> execute` binds to
    the swap intent rather than a per-block quoted output amount, preventing
    harmless repricing from failing execute with `swap_quote_changed`.
  - Raised the default Uniswap slippage floor from `50` bps to `300` bps
    (`3%`) so normal drift during the approval/execution window on Base no
    longer causes avoidable failures. Per-call and env overrides still apply.
- Made the local `wdk-evm-wallet` daemon version-aware and self-refreshing.
  - `/health` now reports the real launcher version instead of a hardcoded
    `0.1.0`.
  - Local EVM autostart compares the running daemon version against the on-disk
    launcher version and automatically restarts a stale daemon after local
    release/install, avoiding old code staying resident in memory.
- Extended the long-running EVM HTTP timeout policy to the Uniswap
  `/v1/evm/uniswap/swap/{quote,send}` routes so approve+swap flows on Base do
  not time out client-side while the daemon is still finishing the on-chain
  operation.

## v0.1.37 - 2026-06-05

- Fixed the Claude Code / Codex MCP bridge failing to start with
  `MCP error -32000: Connection closed` when the plugin is run through a
  marketplace symlink. run_mcp.sh resolved PLUGIN_ROOT with a logical `pwd`, so
  the symlink stayed in the path and the sibling-codex fallback (`../../../codex`)
  collapsed lexically into a non-existent path. The launcher now resolves paths
  physically (`pwd -P`), keeping the `..` arithmetic consistent with the real
  layout, with a regression test that drives the launcher through a symlink.

## v0.1.36 - 2026-06-03

- Installer no longer pins a redundant `OPENCLAW_HOME` into the version-controlled
  bundle `.mcp.json` when the install home is the default `~/.openclaw`
  (run_mcp.sh already derives it). Any stale pin is removed so the tracked file
  self-heals to a clean state; non-default homes still pin as before.

## v0.1.35 - 2026-06-03

- Hardened the Codex / Claude Code MCP wallet bridge:
  - Run the blocking wallet CLI subprocess off the event loop
    (`asyncio.to_thread`) so a slow or hung wallet op no longer freezes the MCP
    server — `tools/list`, read-only calls, and cancellation stay responsive.
    The approval-preview cache is now guarded by a lock for concurrent calls.
  - Consume the approved preview after a successful execute, so a duplicate
    execute call cannot silently re-run the operation from stale 15-min approval
    context. A failed execute keeps the preview so retries still work.
  - `set_wallet_backend` commits session network/backend selection only after
    the validating call succeeds, preventing a stale backend + new network mix.
  - Fixed an off-by-one in the Claude Code launcher's sibling-codex fallback
    path so a local checkout resolves `codex/server.py`.
  - Replaced the `py_compile` self-check with a non-writing `ast.parse` check so
    a read-only install dir cannot trigger a false "runtime broken" error.
  - Parse `AGENT_WALLET_CODEX_TIMEOUT` defensively and surface a clean timeout
    error instead of the raw `TimeoutExpired` repr (which echoed argv, including
    the approval token). CLI stdout parsing now tolerates a stray line ahead of
    the JSON result.
  - Codex skill doc parity (`set_wallet_backend` / `set_evm_network`).

## v0.1.34 - 2026-06-02

- Added native ETH support to EVM (Velora) swaps in the wallet runtime.

- Single source of truth for the project version across every framework.
  - Added a canonical root `VERSION` file. All other manifests (npm
    `package.json`, `pyproject.toml`, Python `__version__`, the OpenClaw
    extension, and the Codex / Claude Code / Hermes / wdk plugin manifests) are
    now derived targets, stamped from `VERSION` via `scripts/sync_version.mjs`
    (`npm run version:sync`). This realigned 7 manifests that had drifted to an
    old `0.1.0`.
  - `scripts/check_release_version.mjs` now verifies all 11 manifests against
    `VERSION` (and against the `v*` tag on release), so version drift cannot be
    merged or published. Shared logic lives in `scripts/version_targets.mjs`.
  - `npm run release:local -- <version>` bumps, stamps, verifies, and reinstalls
    the runtime into every local framework (OpenClaw, Codex, Claude Code) from
    the working tree — the same files that ship to npm/ClawHub. `--dry-run`
    previews the steps without changing anything.
  - `wallet status` / `wallet doctor` gained a `runtime_in_sync` signal flagging
    when the installed runtime lags the repo/CLI version (informational; never
    flips doctor's overall ok).

- Added a background "update available" check so agents (and the humans behind
  them) learn when a newer agent-wallet version is published.
  - `agent_wallet/update_check.py` compares the installed `__version__` against
    the latest version on the npm registry. The network call runs in a daemon
    thread and only refreshes a cache (`OPENCLAW_HOME/agent-wallet-runtime/
    update-check.json`) at most once/day for the *next* start — it never blocks
    server startup, and any failure is silently ignored (fail-open).
  - The MCP server (`server.py`) appends a one-time notice to its `instructions`
    when a newer version is cached. Because instructions are read once per
    session, the agent sees it at most once per usage cycle, and a per-version
    daily throttle prevents repeats across sessions.
  - `wallet status` now includes an `update_available` block and `wallet doctor`
    adds an informational `update_available` check (with a ready `fix` command);
    neither flips doctor's overall `ok`.
  - Opt out entirely with `AGENT_WALLET_DISABLE_UPDATE_CHECK=1`.
  - `agent_wallet/__init__.py` now carries `__version__`, and
    `scripts/check_release_version.mjs` enforces that it stays in sync with
    `package.json` / `pyproject.toml` on release.

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
