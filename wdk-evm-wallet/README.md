# WDK EVM Wallet

Separate EVM wallet service built on top of Tether WDK.

This project is intentionally isolated from the existing Python `agent-wallet/`,
the Solana backend, and the separate BTC runtime. It is the dedicated local EVM
wallet path for ordinary EVM accounts based on `@tetherto/wdk-wallet-evm`.

Current scope:

- local encrypted wallet vault
- localhost-only HTTP surface
- local bearer-token auth between the wallet service and trusted local callers
- wallet registry with `walletId`
- explicit `unlock` / `lock` semantics
- derive EVM accounts and addresses
- fetch native balances
- fetch ERC-20 balances
- fetch fee-rate suggestions
- quote and send native transfers
- quote and send ERC-20 transfers
- fetch transaction receipts

The implementation follows the official WDK documentation:

- Node.js Quickstart: https://docs.wdk.tether.io/start-building/nodejs-bare-quickstart
- SDK Get Started: https://docs.wdk.tether.io/sdk/get-started
- EVM wallet overview: https://docs.wdk.tether.io/sdk/wallet-modules/wallet-evm
- EVM wallet configuration: https://docs.wdk.tether.io/sdk/wallet-modules/wallet-evm/configuration
- EVM wallet API reference: https://docs.wdk.tether.io/sdk/wallet-modules/wallet-evm/api-reference

## Why Separate

- keeps the existing Solana wallet backend untouched
- keeps BTC and EVM custody paths operationally separate
- avoids mixing Python wallet policy with the Node.js WDK runtime
- creates a clean path for future EVM-specific protocol layers without exposing raw contract calls to the agent

## Initial Safety Boundaries

This service intentionally supports a narrow surface:

- normal EVM account model only
- no ERC-4337 in this runtime
- no arbitrary calldata on `sendTransaction`
- no token approvals
- no generic contract execution endpoints
- no seed phrase exposure in the agent-facing path

## Networks

- `ethereum`
- `sepolia`
- `base`
- `base-sepolia`

The active network is persistent and can be switched without changing code.

## API

- `GET /health`
- `GET /v1/evm/network`
- `POST /v1/evm/network/set`
- `POST /v1/evm/seed-phrase/generate`
- `GET /v1/evm/wallets`
- `POST /v1/evm/wallets/get`
- `POST /v1/evm/wallets/create`
- `POST /v1/evm/wallets/import`
- `POST /v1/evm/wallets/unlock`
- `POST /v1/evm/wallets/lock`
- `POST /v1/evm/wallets/reveal-seed`
- `POST /v1/evm/wallets/change-password`
- `POST /v1/evm/address/resolve`
- `POST /v1/evm/balance/get`
- `POST /v1/evm/token-balance/get`
- `POST /v1/evm/fee-rates/get`
- `POST /v1/evm/transaction/receipt/get`
- `POST /v1/evm/transfer/quote`
- `POST /v1/evm/transfer/send`
- `POST /v1/evm/token-transfer/quote`
- `POST /v1/evm/token-transfer/send`

All routes except `/health` require:

- `Authorization: Bearer <token>`

By default the service generates that token automatically at:

- `~/.openclaw/wdk-evm-wallet/local-auth-token`

or under `OPENCLAW_HOME/wdk-evm-wallet/local-auth-token` when `OPENCLAW_HOME` is set.

## Install

```bash
cd wdk-evm-wallet
npm install
cp .env.example .env
npm start
```

Simplest onboarding:

```bash
cd wdk-evm-wallet && sh bootstrap.sh
cd wdk-evm-wallet && npm start
```

Fastest local start:

```bash
cd wdk-evm-wallet && sh run-local.sh
```

## Configuration

Environment variables:

- `HOST`
- `PORT`
- `WDK_EVM_NETWORK`
- `WDK_EVM_DATA_DIR`
- `WDK_EVM_LOCAL_TOKEN`
- `WDK_EVM_LOCAL_TOKEN_PATH`
- `WDK_EVM_UNLOCK_TIMEOUT_SECONDS`
- `WDK_EVM_TRANSFER_MAX_FEE_WEI`
- `WDK_EVM_ETHEREUM_RPC_URL`
- `WDK_EVM_SEPOLIA_RPC_URL`
- `WDK_EVM_BASE_RPC_URL`
- `WDK_EVM_BASE_SEPOLIA_RPC_URL`

Local security note:

- the service binds to `127.0.0.1` by default
- encrypted wallet files are stored locally on disk
- unlocked seed phrases live only in memory
- explicit `lock` or process restart clears the in-memory unlocked state
- seed reveal is password-gated and separate from normal agent operations
