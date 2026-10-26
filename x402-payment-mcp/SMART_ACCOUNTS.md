# Managed CDP smart wallet implementation

Decision, 2026-10-26: Google/GitHub identifies users; a managed CDP EOA owns each
user's native smart account. The smart address receives funds and executes calls
on Ethereum/Base. No passkeys, Arc tools, session keys, fund migration or production
deployment are part of this change. Legacy records remain available for rollback.

## Builder approach

- viem: normalize amounts/addresses, encode/decode ABI and use sequential RPC
  simulation. Independent eth_call or Multicall3 cannot replace dependent batches.
- permissionless.js: separate account-specific execution from generic calls and
  business intent. CDP is our execution adapter; no second account SDK required.
- Safe Core SDK: separate transaction creation, authorization and execution;
  preserve exact ordered calls in a durable preview.
- Keypo: generic to/value/data execution can compose protocol calls; skills
  supply calldata, not authority or guarantees of financial safety.
- Biconomy: runtime injection differs from static batching. No dynamic parameters,
  cross-chain flow or automatic deposit of unknown swap outputs in this version.

The host/chat workflow obtains human consent. An MCP invocation is not independent
cryptographic proof of human approval. Our managed backend can request signatures;
CDP secures keys. Our server owns previews, policies and reconciliation.

## Compatibility

SDK 1.55.0 has smart-account signature wrapping. Its x402 smart-account helper
supports exact/EIP-3009 only. Initially disable other schemes and never fall back
to owner EOA payments. SIWx must not identify the owner as the payment wallet.

Existing OAuth/PAT grants retain x402 scope. Contract tools require a newly granted
wallet:transact scope. User login alone is not contract-execution authorization.

## References studied

- https://github.com/pimlicolabs/permissionless.js
- https://github.com/safe-global/safe-core-sdk/blob/main/packages/protocol-kit/src/Safe.ts
- https://github.com/wevm/viem/blob/main/src/actions/public/simulateCalls.ts
- https://docs.biconomy.io/overview/abstractjs/composable-batching
- https://github.com/keypo-us/keypo-cli/blob/main/keypo-wallet/src/transaction.rs
- https://docs.cdp.coinbase.com/wallets/using-wallets/create-and-manage-wallets

SDKs above are references, not new runtime dependencies. CDP/viem are pinned in
package-lock.json. Live deployments and payments need separate validation.
