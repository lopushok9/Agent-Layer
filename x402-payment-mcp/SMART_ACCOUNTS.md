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

## Managed swap alternative (2026-10-27)

CDP `swap()` is exposed as swap_preview/swap_execute under wallet:transact.
Preview uses a non-binding price. Execution obtains a fresh quote and validates
the approved input/output floor before passing the checked quote into SDK swap().
We deliberately do not use the blind inline overload: it cannot inspect a newly
generated route against the chat-approved floor before Permit2 signing.

The existing operation ledger and network lock are shared with generic calls.
Operation kinds prevent using the wrong execution tool. The quote is recorded
before the SDK's direct Permit2 API signature, and the userOp hash before its
owner signature. Unknown Permit2 outcomes without a hash require operator
reconciliation. ERC-20 approvals remain separately previewed/confirmed; no hidden
approval transaction, EOA fallback or silent unlimited allowance is introduced.

References: https://docs.cdp.coinbase.com/wallets/using-wallets/swaps and
https://docs.cdp.coinbase.com/trade-api/quickstart . Native ETH uses the documented
sentinel address; only Ethereum/Base mainnets are exposed here.

## References studied

- https://github.com/pimlicolabs/permissionless.js
- https://github.com/safe-global/safe-core-sdk/blob/main/packages/protocol-kit/src/Safe.ts
- https://github.com/wevm/viem/blob/main/src/actions/public/simulateCalls.ts
- https://docs.biconomy.io/overview/abstractjs/composable-batching
- https://github.com/keypo-us/keypo-cli/blob/main/keypo-wallet/src/transaction.rs
- https://docs.cdp.coinbase.com/wallets/using-wallets/create-and-manage-wallets

SDKs above are references, not new runtime dependencies. CDP/viem are pinned in
package-lock.json. Live deployments and payments need separate validation.

## Base mainnet probe, 2026-10-27

Smart-account deployment and an exact USDC Permit2 approval were confirmed via
the matching EntryPoint event. The probe exposed a JSONB object-key ordering
false rejection in fresh-simulation comparison; structural comparison fixes it,
with a real Postgres regression test covering changed tokens and amounts too.

The first managed swap remains unresolved: CDP reports `signed` without an
onchain transaction. Its router call simulated successfully at a historical
block, but now reverts with `SignatureExpired`. The initial failure handler did
not retain the provider's error category, so the original submission failure is
not established. Error-category/correlation diagnostics and provider-state output
have since been added. Expiry alone does not unlock a signed operation. Managed
swap end-to-end mainnet execution is not yet validated; reconcile the existing
operation before authorizing a new attempt.
