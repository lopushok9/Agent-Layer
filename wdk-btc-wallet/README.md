# WDK BTC Wallet

Separate BTC-only wallet service built on top of Tether WDK.

This project is intentionally isolated from the existing Python `agent-wallet/`.
It is the first step toward a second wallet backend for non-Solana assets, starting
with Bitcoin only.

Current scope:

- local encrypted wallet vault
- wallet registry with `walletId`
- explicit `unlock` / `lock` semantics
- derive BTC accounts and addresses
- fetch BTC balances
- fetch BTC transfer history
- fetch BTC fee rates
- compute max spendable BTC
- estimate BTC transfer cost
- send BTC transactions

The implementation is based on the official WDK documentation:

- Node.js Quickstart: https://docs.wdk.tether.io/start-building/nodejs-bare-quickstart
- SDK Get Started: https://docs.wdk.tether.io/sdk/get-started
- BTC wallet configuration: https://docs.wdk.tether.io/sdk/wallet-modules/wallet-btc/configuration
- WDK concepts: https://docs.wdk.tether.io/resources-and-guides/concepts

## Why Separate

- keeps the existing Solana wallet untouched
- avoids mixing Python wallet policy with a Node.js SDK runtime
- creates a clean path for a future second wallet backend

## API

- `GET /health`
- `GET /v1/btc/network`
- `POST /v1/btc/network/set`
- `POST /v1/btc/seed-phrase/generate`
- `GET /v1/btc/wallets`
- `POST /v1/btc/wallets/get`
- `POST /v1/btc/wallets/create`
- `POST /v1/btc/wallets/import`
- `POST /v1/btc/wallets/unlock`
- `POST /v1/btc/wallets/lock`
- `POST /v1/btc/wallets/reveal-seed`
- `POST /v1/btc/wallets/change-password`
- `POST /v1/btc/address/resolve`
- `POST /v1/btc/balance/get`
- `POST /v1/btc/transfers/get`
- `POST /v1/btc/max-spendable/get`
- `POST /v1/btc/fee-rates/get`
- `POST /v1/btc/transfer/quote`
- `POST /v1/btc/transfer/send`

The preferred flow is now local-vault based:

1. create or import a wallet
2. get a `walletId`
3. the wallet is auto-unlocked locally
4. call BTC operations using `walletId`

The service also has a persistent active Bitcoin network:

- `bitcoin` for mainnet
- `testnet` for public test BTC
- `regtest` for local-only development

You can switch the active network without changing code.

Raw `seedPhrase` input is still accepted as a transitional developer path, but it is
no longer the intended local-wallet model.

`unlock` remains available for two cases only:

- after an explicit `lock`
- after process restart, because unlocked seed phrases live only in memory

## Install

```bash
cd wdk-btc-wallet
npm install
cp .env.example .env
npm start
```

## Configuration

Environment variables:

- `HOST`
- `PORT`
- `WDK_BTC_NETWORK`
- `WDK_BTC_BIP`
- `WDK_BTC_BITCOIN_ELECTRUM_PROTOCOL`
- `WDK_BTC_BITCOIN_ELECTRUM_HOST`
- `WDK_BTC_BITCOIN_ELECTRUM_PORT`
- `WDK_BTC_TESTNET_ELECTRUM_PROTOCOL`
- `WDK_BTC_TESTNET_ELECTRUM_HOST`
- `WDK_BTC_TESTNET_ELECTRUM_PORT`
- `WDK_BTC_REGTEST_ELECTRUM_PROTOCOL`
- `WDK_BTC_REGTEST_ELECTRUM_HOST`
- `WDK_BTC_REGTEST_ELECTRUM_PORT`
- `WDK_BTC_DATA_DIR`
- `WDK_BTC_UNLOCK_TIMEOUT_SECONDS`

Production note from WDK docs:

- public Electrum servers are convenient, but slower and less reliable
- production should use your own Electrum/Fulcrum server

Local security note:

- the service now binds to `127.0.0.1` by default
- encrypted wallet files are stored locally on disk
- unlocked seed phrases live only in memory
- by default the unlocked session does not expire automatically
- explicit `lock` or process restart clears the in-memory unlocked state
- seed reveal is password-gated and separate from normal agent operations

## Example Requests

Generate a seed phrase:

```bash
curl http://localhost:8080/v1/btc/seed-phrase/generate \
  -H "Content-Type: application/json" \
  -d '{"words": 12}'
```

The service intentionally exposes only documented WDK seed generation behavior, so `12`
is the only supported word count right now.

Read the active Bitcoin network:

```bash
curl http://127.0.0.1:8080/v1/btc/network
```

Switch to testnet:

```bash
curl http://127.0.0.1:8080/v1/btc/network/set \
  -H "Content-Type: application/json" \
  -d '{"network":"testnet"}'
```

All subsequent wallet operations use that active network unless an explicit `network`
override is passed in the request body.

Create a local encrypted wallet:

```bash
curl http://127.0.0.1:8080/v1/btc/wallets/create \
  -H "Content-Type: application/json" \
  -d '{"label":"My BTC Wallet","password":"strong-local-password","words":12}'
```

This returns a `walletId` and leaves the wallet unlocked locally right away.
By default it does not return the seed phrase. If a host UI needs first-run backup UX,
it should request and display it explicitly rather than exposing it to the agent path.

Reveal the seed phrase for backup or recovery:

```bash
curl http://127.0.0.1:8080/v1/btc/wallets/reveal-seed \
  -H "Content-Type: application/json" \
  -d '{"walletId":"replace-with-wallet-id","password":"strong-local-password"}'
```

This endpoint is intended for the host/UI only. The agent-facing flow should keep
using `walletId` and should not need to see the password or the seed phrase.

List wallets:

```bash
curl http://127.0.0.1:8080/v1/btc/wallets
```

Get a single wallet's metadata:

```bash
curl http://127.0.0.1:8080/v1/btc/wallets/get \
  -H "Content-Type: application/json" \
  -d '{"walletId":"replace-with-wallet-id"}'
```

Unlock a wallet after restart or explicit lock:

```bash
curl http://127.0.0.1:8080/v1/btc/wallets/unlock \
  -H "Content-Type: application/json" \
  -d '{"walletId":"replace-with-wallet-id","password":"strong-local-password"}'
```

Rotate the wallet password:

```bash
curl http://127.0.0.1:8080/v1/btc/wallets/change-password \
  -H "Content-Type: application/json" \
  -d '{
    "walletId":"replace-with-wallet-id",
    "currentPassword":"old-password",
    "newPassword":"new-password"
  }'
```

If the wallet is already unlocked locally, password rotation keeps it unlocked.

Resolve the first BTC address:

```bash
curl http://127.0.0.1:8080/v1/btc/address/resolve \
  -H "Content-Type: application/json" \
  -d '{"walletId":"replace-with-wallet-id","accountIndex":0}'
```

To force a one-off request to testnet without changing the active network:

```bash
curl http://127.0.0.1:8080/v1/btc/address/resolve \
  -H "Content-Type: application/json" \
  -d '{"walletId":"replace-with-wallet-id","accountIndex":0,"network":"testnet"}'
```

Get the BTC balance:

```bash
curl http://127.0.0.1:8080/v1/btc/balance/get \
  -H "Content-Type: application/json" \
  -d '{"walletId":"replace-with-wallet-id","accountIndex":0}'
```

Get BTC transfer history:

```bash
curl http://127.0.0.1:8080/v1/btc/transfers/get \
  -H "Content-Type: application/json" \
  -d '{
    "walletId":"replace-with-wallet-id",
    "accountIndex":0,
    "direction":"all",
    "limit":10,
    "skip":0
  }'
```

Get BTC fee rates:

```bash
curl http://127.0.0.1:8080/v1/btc/fee-rates/get \
  -H "Content-Type: application/json" \
  -d '{}'
```

Get max spendable BTC:

```bash
curl http://127.0.0.1:8080/v1/btc/max-spendable/get \
  -H "Content-Type: application/json" \
  -d '{"walletId":"replace-with-wallet-id","accountIndex":0}'
```

Estimate a BTC transfer:

```bash
curl http://127.0.0.1:8080/v1/btc/transfer/quote \
  -H "Content-Type: application/json" \
  -d '{
    "walletId":"replace-with-wallet-id",
    "accountIndex":0,
    "to":"bc1...",
    "value":10000
  }'
```

## Notes

- WDK BTC docs describe BIP-84 as the current default.
- WDK BTC docs also note a historical derivation-path change from legacy BIP-44.
- If you need to recreate older wallets, use an explicit derivation path or set `WDK_BTC_BIP=44`.
- The service currently follows the documented `WalletManagerBtc` and `WalletAccountBtc` API surface only.
- The local vault is intentionally file-based and cross-platform; it does not depend on Apple Secure Enclave.
- The intended host-managed mode is: user enters password, agent uses only `walletId`, password never needs to be exposed to the agent.
- Mainnet/testnet/regtest switching is runtime-configurable; active network state is stored locally under the wallet data directory.
