# Graph Report - agent-wallet  (2026-04-19)

## Corpus Check
- 104 files · ~76,627 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 1350 nodes · 3602 edges · 53 communities detected
- Extraction: 59% EXTRACTED · 41% INFERRED · 0% AMBIGUOUS · INFERRED: 1463 edges (avg confidence: 0.72)
- Token cost: 0 input · 0 output

## Community Hubs (Navigation)
- [[_COMMUNITY_Solana Provider Tests|Solana Provider Tests]]
- [[_COMMUNITY_Backend Capability API|Backend Capability API]]
- [[_COMMUNITY_User Wallet Runtime|User Wallet Runtime]]
- [[_COMMUNITY_Provider HTTP Clients|Provider HTTP Clients]]
- [[_COMMUNITY_Fake Backend Approval|Fake Backend Approval]]
- [[_COMMUNITY_Bootstrap Storage|Bootstrap Storage]]
- [[_COMMUNITY_Sealed Config Keys|Sealed Config Keys]]
- [[_COMMUNITY_Installer Scripts|Installer Scripts]]
- [[_COMMUNITY_Wallet Backend Factory|Wallet Backend Factory]]
- [[_COMMUNITY_Approval Nonce Policy|Approval Nonce Policy]]
- [[_COMMUNITY_BTC Smoke Flows|BTC Smoke Flows]]
- [[_COMMUNITY_EVM Fake Backend|EVM Fake Backend]]
- [[_COMMUNITY_Transaction Policy Parser|Transaction Policy Parser]]
- [[_COMMUNITY_LI.FI Provider|LI.FI Provider]]
- [[_COMMUNITY_Provider Portfolio Layer|Provider Portfolio Layer]]
- [[_COMMUNITY_Solana TX Encoding|Solana TX Encoding]]
- [[_COMMUNITY_Sepolia EVM Transfer|Sepolia EVM Transfer]]
- [[_COMMUNITY_EVM Portfolio Cache|EVM Portfolio Cache]]
- [[_COMMUNITY_Solana Stake Helpers|Solana Stake Helpers]]
- [[_COMMUNITY_Provider Response Tests|Provider Response Tests]]
- [[_COMMUNITY_RPC Failover Tests|RPC Failover Tests]]
- [[_COMMUNITY_Wallet Operator Safety|Wallet Operator Safety]]
- [[_COMMUNITY_Adapter Runtime Tests|Adapter Runtime Tests]]
- [[_COMMUNITY_Sealed Install Tests|Sealed Install Tests]]
- [[_COMMUNITY_OpenClaw Examples|OpenClaw Examples]]
- [[_COMMUNITY_Bags Gateway Tests|Bags Gateway Tests]]
- [[_COMMUNITY_User Wallet Tests|User Wallet Tests]]
- [[_COMMUNITY_WDK Security Tests|WDK Security Tests]]
- [[_COMMUNITY_WDK EVM Test Server|WDK EVM Test Server]]
- [[_COMMUNITY_OpenClaw Runtime Smoke|OpenClaw Runtime Smoke]]
- [[_COMMUNITY_OpenClaw CLI Smoke|OpenClaw CLI Smoke]]
- [[_COMMUNITY_BTC Bootstrap Tests|BTC Bootstrap Tests]]
- [[_COMMUNITY_Approval Policy Tests|Approval Policy Tests]]
- [[_COMMUNITY_BTC Autostart Test|BTC Autostart Test]]
- [[_COMMUNITY_Installer Smoke|Installer Smoke]]
- [[_COMMUNITY_Network Switch Test|Network Switch Test]]
- [[_COMMUNITY_Backend Package Init|Backend Package Init]]
- [[_COMMUNITY_Jupiter Live Reads|Jupiter Live Reads]]
- [[_COMMUNITY_BTC Shell Wrappers|BTC Shell Wrappers]]
- [[_COMMUNITY_CLI Bridge Tests|CLI Bridge Tests]]
- [[_COMMUNITY_WSOL Transfer Test|WSOL Transfer Test]]
- [[_COMMUNITY_Bootstrap Smoke|Bootstrap Smoke]]
- [[_COMMUNITY_BTC Wallet Manager|BTC Wallet Manager]]
- [[_COMMUNITY_Encrypted Storage Test|Encrypted Storage Test]]
- [[_COMMUNITY_Runtime RPC Config|Runtime RPC Config]]
- [[_COMMUNITY_RPC Failover|RPC Failover]]
- [[_COMMUNITY_Solana TX Test|Solana TX Test]]
- [[_COMMUNITY_Sealed Key Test|Sealed Key Test]]
- [[_COMMUNITY_Wallet Network Switching|Wallet Network Switching]]
- [[_COMMUNITY_Package Init|Package Init]]
- [[_COMMUNITY_Wallet Address Capability|Wallet Address Capability]]
- [[_COMMUNITY_Wallet Balance Capability|Wallet Balance Capability]]
- [[_COMMUNITY_Runtime Capabilities|Runtime Capabilities]]

## God Nodes (most connected - your core abstractions)
1. `WalletBackendError` - 348 edges
2. `SolanaWalletBackend` - 148 edges
3. `AgentWalletBackend` - 135 edges
4. `ProviderError` - 105 edges
5. `FakeBackend` - 72 edges
6. `OpenClawWalletAdapter` - 60 edges
7. `WdkEvmLocalWalletBackend` - 40 edges
8. `get_client()` - 37 edges
9. `WalletCapabilities` - 35 edges
10. `WdkEvmLocalClient` - 30 edges

## Surprising Connections (you probably didn't know these)
- `Live Sepolia native transfer smoke` --references--> `Execute approval-token rule`  [INFERRED]
  agent-wallet/tests/live_wdk_evm_sepolia_native_transfer.py → agent-wallet/skills/wallet-operator/SKILL.md
- `Smoke test for user-scoped wallet provisioning.` --uses--> `WalletBackendError`  [INFERRED]
  agent-wallet/tests/smoke_user_wallets.py → agent-wallet/agent_wallet/wallet_layer/base.py
- `Smoke test for boot-key backed sealed secret storage.` --uses--> `WalletBackendError`  [INFERRED]
  agent-wallet/tests/smoke_sealed_keys.py → agent-wallet/agent_wallet/wallet_layer/base.py
- `Smoke test for user wallet backup export and encryption rotation.` --uses--> `WalletBackendError`  [INFERRED]
  agent-wallet/tests/smoke_user_wallet_admin.py → agent-wallet/agent_wallet/wallet_layer/base.py
- `Smoke test for Solana RPC failover behavior.` --uses--> `ProviderError`  [INFERRED]
  agent-wallet/tests/smoke_solana_rpc_failover.py → agent-wallet/agent_wallet/exceptions.py

## Hyperedges (group relationships)
- **Execute approval flow** — openclaw_adapter_require_execute_approval, approval_verify_approval_token, nonce_registry_require_single_use [INFERRED 0.91]
- **Runtime and plugin bundle flow** — openclaw_runtime_onboard_openclaw_user_wallet, plugin_bundle_build_openclaw_plugin_bundle, openclaw_cli_run_onboard [INFERRED 0.77]
- **Stake instruction helper family** — solana_stake_initialize_checked, solana_stake_delegate_stake, solana_stake_deactivate_stake, solana_stake_withdraw_stake [INFERRED 0.83]
- **Solana Provider Transaction Safety Flow** — wallet_layer_solana_backend, transaction_policy_allowlist_gate, spending_limits_ledger, providers_solana_rpc [INFERRED 0.88]
- **Local WDK Backend Pattern** — wallet_layer_wdk_btc_backend, wallet_layer_wdk_evm_backend, providers_wdk_btc_local_client, providers_wdk_evm_local_client [INFERRED 0.90]
- **User Wallet Bootstrap Flow** — bootstrap_wallet_example, user_wallets_per_user_provisioner, wallet_layer_factory, wallet_layer_solana_backend [INFERRED 0.79]
- **OpenClaw runtime integration flow** — openclaw_runtime_onboarding_example, openclaw_user_wallet_example, openclaw_wallet_adapter_example [INFERRED 0.85]
- **OpenClaw install and seal flow** — install_agent_wallet_script, install_openclaw_local_config_script, install_openclaw_sealed_keys_script, finalize_openclaw_local_wallet_config_script, switch_openclaw_wallet_network_script [INFERRED 0.90]
- **Bags provider gateway and execution flow** — smoke_bags_provider_gateway_test, smoke_bags_launch_flow_test, smoke_bags_claim_v3_response_test [INFERRED 0.84]
- **BTC Wallet Bootstrap Flow** — smoke_bootstrap_openclaw_btc_test, smoke_bootstrap_openclaw_btc_autostart_test, smoke_bootstrap_openclaw_btc_mainnet_test, smoke_btc_host_shell_wrappers_test, smoke_manage_openclaw_btc_wallet_test [INFERRED 0.92]
- **Sealed Key Installation Flow** — smoke_install_agent_wallet_test, smoke_install_openclaw_local_config_sealed_test, smoke_install_openclaw_sealed_keys_test, smoke_encrypted_storage_test [INFERRED 0.90]
- **Provider Response Normalization Flow** — smoke_gateway_rpc_public_mode_test, smoke_jupiter_earn_provider_gateway_test, smoke_jupiter_earn_responses_test, smoke_kamino_responses_test [INFERRED 0.84]
- **OpenClaw EVM Smoke Flow** — smoke_openclaw_evm_cli, smoke_openclaw_evm_runtime, openclaw_cli_bridge, openclaw_runtime_onboarding [INFERRED 0.86]
- **User Wallet Lifecycle** — smoke_openclaw_runtime, smoke_user_wallets, smoke_user_wallet_key_derivation, smoke_user_wallet_admin, openclaw_runtime_onboarding [INFERRED 0.84]
- **Local Security Guardrails Flow** — smoke_wdk_btc_local_security, smoke_wdk_evm_local_security, smoke_wdk_evm_error_shaping, wdk_local_security_guardrails [INFERRED 0.80]

## Communities

### Community 0 - "Solana Provider Tests"
Cohesion: 0.03
Nodes (71): b58encode(), Encode bytes into a base58 string., _load_keypair(), main(), Live devnet smoke for SPL transfer using wrapped SOL., _wait_for_owner_token_balance(), _wrap_sol(), main() (+63 more)

### Community 1 - "Backend Capability API"
Cohesion: 0.03
Nodes (51): ABC, AgentWalletBackend, get_address(), get_balance(), get_capabilities(), Shared primitives for agent wallet backends., Wallet backend or signer error., Abstract interface for chain-specific agent wallets. (+43 more)

### Community 2 - "User Wallet Runtime"
Cohesion: 0.04
Nodes (95): create_user_btc_wallet(), get_user_btc_wallet_binding(), import_user_btc_wallet(), lock_user_btc_wallet(), _normalize_btc_network(), Host-side helpers for binding local BTC wallets to OpenClaw users., _resolve_service_url(), resolve_user_btc_wallet_path() (+87 more)

### Community 3 - "Provider HTTP Clients"
Cohesion: 0.05
Nodes (95): build_claim_transactions(), build_swap_transaction(), create_fee_share_config(), create_launch_transaction(), create_token_info(), fetch_claim_events(), fetch_claim_stats(), fetch_claimable_positions() (+87 more)

### Community 4 - "Fake Backend Approval"
Cohesion: 0.02
Nodes (13): Capability summary exposed by wallet backends., WalletCapabilities, FakeBackend, DriftingSwapBackend, FakeBackend, _issue_execute_approval(), main(), MainnetFakeBackend (+5 more)

### Community 5 - "Bootstrap Storage"
Cohesion: 0.04
Nodes (81): create_solana_wallet_file(), describe_bootstrap(), ensure_solana_wallet_ready(), ensure_wallet_pin(), generate_solana_wallet_material(), _keypair_bytes_for_file(), load_wallet_pin(), Bootstrap helpers for provisioning agent wallets on first use. (+73 more)

### Community 6 - "Sealed Config Keys"
Cohesion: 0.04
Nodes (73): BaseSettings, allow_plaintext_user_wallet_migration(), _build_provider_gateway_rpc_url(), _env_bool(), _normalize_provider_mode(), _normalize_rpc_provider(), _normalize_swap_provider(), Configuration for agent wallet backends. (+65 more)

### Community 7 - "Installer Scripts"
Cohesion: 0.07
Nodes (47): _auto_start_local_service(), build_parser(), _default_config_path(), _default_python_bin(), _default_user_id(), _ensure_openclaw_config(), _health_url(), _is_local_service_url() (+39 more)

### Community 8 - "Wallet Backend Factory"
Cohesion: 0.11
Nodes (18): AgentWalletBackend, create_wallet_backend(), _load_keypair_material(), Factory helpers for agent wallet backends., Build the configured wallet backend instance., _normalize_btc_network(), _sats_to_btc(), WdkBtcLocalWalletBackend (+10 more)

### Community 9 - "Approval Nonce Policy"
Cohesion: 0.07
Nodes (35): Authoritative Python backend and safety policy, OpenClaw bridge alignment rule, Backend-first wallet architecture, Raw RPC + local signer first, Hosted provider gateway reduces onboarding friction, Preview-prepare-execute safety contract, _approval_secret(), build_operation_binding() (+27 more)

### Community 10 - "BTC Smoke Flows"
Cohesion: 0.06
Nodes (35): OpenClaw BTC bootstrap script, BTC wallet binding flow, Fake WDK BTC service runner, main(), Standalone runner for the fake WDK BTC service used by bootstrap smokes., Finalize OpenClaw wallet config, Agent wallet installer, OpenClaw local config patcher (+27 more)

### Community 11 - "EVM Fake Backend"
Cohesion: 0.14
Nodes (2): FakeEvmBackend, _main()

### Community 12 - "Transaction Policy Parser"
Cohesion: 0.19
Nodes (18): _Header, _Instruction, main(), _Message, Smoke tests for provider transaction verification policy., _account_keys(), _assert_basic_wallet_binding(), _assert_program_allowlist() (+10 more)

### Community 13 - "LI.FI Provider"
Cohesion: 0.2
Nodes (15): _base_url(), chain_name_for_id(), _clean_params(), _csv(), fetch_quote(), fetch_supported_chains(), fetch_transfer_status(), format_openclaw_supported_chains() (+7 more)

### Community 14 - "Provider Portfolio Layer"
Cohesion: 0.14
Nodes (20): Bootstrap Wallet Example, Bags Gateway Client, EVM Portfolio Snapshotter, Jupiter Provider, Kamino Provider, LI.FI Router, Solana JSON-RPC Provider, WDK BTC Local Client (+12 more)

### Community 15 - "Solana TX Encoding"
Cohesion: 0.16
Nodes (13): b58decode(), Minimal base58 helpers to avoid extra runtime dependencies., Decode a base58 string into bytes., main(), Basic serialization test for the minimal Solana transfer builder., _decode_secret_material(), build_legacy_sol_transfer_message(), encode_shortvec() (+5 more)

### Community 16 - "Sepolia EVM Transfer"
Cohesion: 0.4
Nodes (12): _amount_wei(), _config(), _invoke(), _issue_approval(), main(), _prepare_isolated_openclaw_home(), Live Sepolia smoke for the local EVM wallet prepare/execute flow.  This test is, _recipient() (+4 more)

### Community 17 - "EVM Portfolio Cache"
Cohesion: 0.31
Nodes (12): build_portfolio_snapshot(), _cache_get_price(), _cache_get_token_balances(), _cache_set_price(), _cache_set_token_balances(), fetch_token_balances(), fetch_usd_prices(), _format_decimal() (+4 more)

### Community 18 - "Solana Stake Helpers"
Cohesion: 0.26
Nodes (10): deactivate_stake(), delegate_stake(), initialize_checked(), Helpers for native Solana stake program instructions., Build InitializeChecked for a new stake account., Build DelegateStake for an initialized stake account., Build Deactivate for a delegated stake account., Build Withdraw for an inactive or partially withdrawable stake account. (+2 more)

### Community 19 - "Provider Response Tests"
Cohesion: 0.25
Nodes (4): providers.jupiter, providers.kamino, providers.solana_rpc, wallet_layer.solana

### Community 20 - "RPC Failover Tests"
Cohesion: 0.29
Nodes (6): main(), Smoke test for provider-gateway RPC mode without bearer auth., _run(), main(), Smoke test for Solana RPC failover behavior., _run()

### Community 21 - "Wallet Operator Safety"
Cohesion: 0.29
Nodes (8): Execute approval-token rule, LI.FI cross-chain policy, Mainnet confirmation rationale, Mainnet confirmation rule, No Mayan policy, Preview-first safety rationale, Preview-first rule, Wallet operator skill

### Community 22 - "Adapter Runtime Tests"
Cohesion: 0.32
Nodes (3): btc_user_wallets, openclaw_adapter, openclaw_runtime

### Community 23 - "Sealed Install Tests"
Cohesion: 0.33
Nodes (1): sealed_keys

### Community 24 - "OpenClaw Examples"
Cohesion: 0.4
Nodes (6): OpenClaw safe adapter dispatch flow, Per-user wallet backend flow, OpenClaw runtime onboarding example, OpenClaw runtime onboarding flow, OpenClaw user wallet example, OpenClaw wallet adapter example

### Community 25 - "Bags Gateway Tests"
Cohesion: 0.47
Nodes (6): Bags fee claim flow, Bags provider gateway flow, Bags token launch flow, Bags claim v3 response smoke, Bags token launch smoke, Bags provider gateway smoke

### Community 26 - "User Wallet Tests"
Cohesion: 0.47
Nodes (3): User Wallet Encryption Admin, User Wallet Key Derivation, User Wallet Provisioning

### Community 27 - "WDK Security Tests"
Cohesion: 0.53
Nodes (3): WDK BTC Local Security, WDK EVM Error Shaping, WDK Local Security Guardrails

### Community 28 - "WDK EVM Test Server"
Cohesion: 0.5
Nodes (3): chain_id(), chain_id_for(), Small fake local HTTP server for wdk-evm-wallet integration tests.

### Community 29 - "OpenClaw Runtime Smoke"
Cohesion: 0.6
Nodes (2): OpenClaw CLI Bridge, OpenClaw Runtime Onboarding

### Community 30 - "OpenClaw CLI Smoke"
Cohesion: 0.67
Nodes (3): main(), Smoke test for the OpenClaw CLI bridge., _run()

### Community 31 - "BTC Bootstrap Tests"
Cohesion: 0.83
Nodes (0): 

### Community 32 - "Approval Policy Tests"
Cohesion: 0.5
Nodes (2): Host Approval Token Flow, Transaction Verification Policy

### Community 33 - "BTC Autostart Test"
Cohesion: 0.67
Nodes (1): Smoke test for auto-starting the local WDK BTC service during bootstrap.

### Community 34 - "Installer Smoke"
Cohesion: 0.67
Nodes (1): Smoke test for the one-command agent-wallet installer.

### Community 35 - "Network Switch Test"
Cohesion: 0.67
Nodes (1): Smoke test for switching the configured OpenClaw wallet network.

### Community 36 - "Backend Package Init"
Cohesion: 0.67
Nodes (1): Plugin-friendly agent wallet backends.

### Community 37 - "Jupiter Live Reads"
Cohesion: 1.0
Nodes (3): Live Jupiter prices smoke, Live Jupiter quote smoke, Read-only Jupiter market reads

### Community 38 - "BTC Shell Wrappers"
Cohesion: 0.67
Nodes (0): 

### Community 39 - "CLI Bridge Tests"
Cohesion: 1.0
Nodes (1): openclaw_cli

### Community 40 - "WSOL Transfer Test"
Cohesion: 1.0
Nodes (2): Live devnet WSOL SPL transfer smoke, Solana preview/send transfer flow

### Community 41 - "Bootstrap Smoke"
Cohesion: 1.0
Nodes (1): create_solana_wallet_file

### Community 42 - "BTC Wallet Manager"
Cohesion: 1.0
Nodes (0): 

### Community 43 - "Encrypted Storage Test"
Cohesion: 1.0
Nodes (1): encrypted_storage

### Community 44 - "Runtime RPC Config"
Cohesion: 1.0
Nodes (1): Runtime Solana RPC Config

### Community 45 - "RPC Failover"
Cohesion: 1.0
Nodes (1): Solana RPC Failover

### Community 46 - "Solana TX Test"
Cohesion: 1.0
Nodes (1): Solana TX Serialization

### Community 47 - "Sealed Key Test"
Cohesion: 1.0
Nodes (1): Sealed Secret Loading

### Community 48 - "Wallet Network Switching"
Cohesion: 1.0
Nodes (1): Wallet Network Switching

### Community 49 - "Package Init"
Cohesion: 1.0
Nodes (0): 

### Community 50 - "Wallet Address Capability"
Cohesion: 1.0
Nodes (1): Return the wallet address if one is configured.

### Community 51 - "Wallet Balance Capability"
Cohesion: 1.0
Nodes (1): Return the wallet balance for the configured or provided address.

### Community 52 - "Runtime Capabilities"
Cohesion: 1.0
Nodes (1): Describe backend capabilities for the agent runtime.

## Knowledge Gaps
- **94 isolated node(s):** `Smoke test for auto-starting the local WDK BTC service during bootstrap.`, `Smoke coverage for Jupiter Earn provider gateway routing.`, `Basic serialization test for the minimal Solana transfer builder.`, `Smoke test for the sealed-keys installer script.`, `Smoke test for provider-gateway RPC mode without bearer auth.` (+89 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **Thin community `WSOL Transfer Test`** (2 nodes): `Live devnet WSOL SPL transfer smoke`, `Solana preview/send transfer flow`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Bootstrap Smoke`** (2 nodes): `create_solana_wallet_file`, `smoke_bootstrap.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `BTC Wallet Manager`** (2 nodes): `manage_openclaw_btc_wallet.py`, `smoke_manage_openclaw_btc_wallet.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Encrypted Storage Test`** (2 nodes): `encrypted_storage`, `smoke_encrypted_storage.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Runtime RPC Config`** (2 nodes): `Runtime Solana RPC Config`, `smoke_runtime_rpc_config.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `RPC Failover`** (2 nodes): `smoke_solana_rpc_failover.py`, `Solana RPC Failover`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Solana TX Test`** (2 nodes): `smoke_solana_tx.py`, `Solana TX Serialization`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Sealed Key Test`** (2 nodes): `Sealed Secret Loading`, `smoke_sealed_keys.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Wallet Network Switching`** (2 nodes): `smoke_switch_openclaw_wallet_network.py`, `Wallet Network Switching`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Package Init`** (1 nodes): `__init__.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Wallet Address Capability`** (1 nodes): `Return the wallet address if one is configured.`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Wallet Balance Capability`** (1 nodes): `Return the wallet balance for the configured or provided address.`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Runtime Capabilities`** (1 nodes): `Describe backend capabilities for the agent runtime.`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `WalletBackendError` connect `Backend Capability API` to `Solana Provider Tests`, `User Wallet Runtime`, `Provider HTTP Clients`, `Bootstrap Storage`, `Sealed Config Keys`, `Wallet Backend Factory`, `Approval Nonce Policy`, `BTC Smoke Flows`, `EVM Fake Backend`, `Transaction Policy Parser`, `LI.FI Provider`, `Solana TX Encoding`?**
  _High betweenness centrality (0.410) - this node is a cross-community bridge._
- **Why does `FakeBackend` connect `Fake Backend Approval` to `Wallet Backend Factory`, `Backend Capability API`?**
  _High betweenness centrality (0.099) - this node is a cross-community bridge._
- **Why does `OpenClawWalletAdapter` connect `Backend Capability API` to `User Wallet Runtime`, `EVM Fake Backend`, `Fake Backend Approval`?**
  _High betweenness centrality (0.084) - this node is a cross-community bridge._
- **Are the 259 inferred relationships involving `WalletBackendError` (e.g. with `Smoke test for user-scoped wallet provisioning.` and `FakeEvmBackend`) actually correct?**
  _`WalletBackendError` has 259 INFERRED edges - model-reasoned connections that need verification._
- **Are the 34 inferred relationships involving `SolanaWalletBackend` (e.g. with `Regression smoke test for native stake prepare path.` and `Live devnet smoke for SPL transfer using wrapped SOL.`) actually correct?**
  _`SolanaWalletBackend` has 34 INFERRED edges - model-reasoned connections that need verification._
- **Are the 43 inferred relationships involving `AgentWalletBackend` (e.g. with `FakeBtcBackend` and `Smoke test for the OpenClaw BTC adapter surface.`) actually correct?**
  _`AgentWalletBackend` has 43 INFERRED edges - model-reasoned connections that need verification._
- **Are the 101 inferred relationships involving `ProviderError` (e.g. with `Smoke test for Solana RPC failover behavior.` and `LI.FI cross-chain quote and status provider.`) actually correct?**
  _`ProviderError` has 101 INFERRED edges - model-reasoned connections that need verification._