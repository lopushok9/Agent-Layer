# Managed CDP smart wallet implementation

Decision, 2026-10-26: Google/GitHub identifies users; a managed CDP EOA owns each
user's native smart account. The smart address receives funds and executes calls
on Ethereum/Base. No passkeys, Arc tools, session keys, fund migration are introduced. Production rollout was authorized separately. Legacy records remain available for rollback.

## Builder approach

- viem: normalize amounts/addresses, encode/decode ABI and use sequential RPC
  simulation. Independent eth_call or Multicall3 cannot replace dependent batches.
- permissionless.js: separate account-specific execution from generic calls and
  business intent. viem now builds UserOperations; Alchemy sends them and CDP signs.
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

CDP quotes are exposed through swap_preview/swap_execute under wallet:transact.
Preview uses a non-binding price. Execution obtains a fresh quote and validates
the approved input/output floor before signing Permit2. New operations use
viem/Alchemy instead of the opaque CDP SDK swap submission path.

The existing operation ledger and network lock are shared with generic calls.
Operation kinds prevent using the wrong execution tool. The quote is recorded
before Permit2 signing, and the full encrypted UserOperation plus hash before
its owner signature. Unknown Permit2 outcomes without a hash require operator
reconciliation. ERC-20 approvals remain separately previewed/confirmed; no hidden
approval transaction, EOA fallback or silent unlimited allowance is introduced.

References: https://docs.cdp.coinbase.com/wallets/using-wallets/swaps and
https://docs.cdp.coinbase.com/trade-api/quickstart . Native ETH uses the documented
sentinel address; only Ethereum/Base mainnets are exposed here.

## Verified ABIs and ERC-7730 display (2026-10-28)

Previews used to trust whatever ABI the agent supplied, or show raw bytes. They
now resolve the target like Otterscan and Sourcify do with WhatsABI 0.29
(`autoload` with `followProxies`, Sourcify then Etherscan v2 loaders, OpenChain
and 4byte only as a labelled fallback) and render ERC-7730 descriptors with
`@ethereum-sourcify/clear-signing` 0.2 against the registry's prebuilt index
(cached 6h; contracts cached 10 min). Resolution failures degrade to the old
labels, never block a preview, and never alter calldata or fingerprints.

## Off-chain signatures (2026-10-28)

signature_prepare/signature_execute reuse the preview model of contract calls
for EIP-191 and EIP-712. Signing goes through viem's toCoinbaseSmartAccount
(replay-safe hash, ERC-6492 when undeployed) with the CDP owner, as the Permit2
swap path already did, and is checked with viem verifyTypedData/verifyMessage
before it is returned. Base mainnet check with a local owner key on an
undeployed v1.1 account: the ERC-6492 signature verifies, a tampered message and
a bare owner-EOA signature do not.

## References studied

- https://github.com/pimlicolabs/permissionless.js
- https://github.com/safe-global/safe-core-sdk/blob/main/packages/protocol-kit/src/Safe.ts
- https://github.com/wevm/viem/blob/main/src/actions/public/simulateCalls.ts
- https://docs.biconomy.io/overview/abstractjs/composable-batching
- https://github.com/keypo-us/keypo-cli/blob/main/keypo-wallet/src/transaction.rs
- https://docs.cdp.coinbase.com/wallets/using-wallets/create-and-manage-wallets

- https://github.com/shazow/whatsabi (proxy resolution, ABI loaders)
- https://github.com/sourcifyeth/clear-signing (ERC-7730 reference renderer)
- https://github.com/ethereum/clear-signing-erc7730-registry

WhatsABI and clear-signing are runtime dependencies; the other SDKs above are references. CDP/viem are pinned in
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


## Execution adapter change and cancellation, 2026-10-27

User approved viem + Alchemy execution while retaining CDP keys. The existing
account address, owner, login and x402 signer remain unchanged. Factory v1.1/salt
zero is independently derived and compared with the CDP registry; unsupported
account configurations fail before signing. There is no owner-EOA send fallback.

The new executor persists full, hash-verified unsigned UserOperations encrypted
with a dedicated deployment key. Account calls use nonce lane 0. A separately
confirmed cancellation uses lane 1 to call EntryPoint.incrementNonce(0), then
requires finalized inclusion, nonce advancement, Permit2 expiry and a nonce-based
location of the original (Otterscan-style binary search over getNonce) before
atomically resolving both ledger rows. A stalled cancellation is replaced at its
own nonce with higher fees rather than cancelled in a new lane.
See README for tool names, funding, configuration and reconciliation limits.

Read-only Base mainnet validation successfully derived the existing account and
prepared an unsigned balanceOf operation through Alchemy at nonce 1, with total
ERC-4337 gas estimate 137607 and maxFeePerGas 7000000 wei at the sampled block.
The probe stopped before persistence/signing and did not broadcast. These numbers
are observations, not current fee quotes. End-to-end execution/cancellation still
requires a separately confirmed mainnet transaction.

The old opaque swap remains blocked. Its CDP status is signed; Alchemy's
eth_getUserOperationByHash returned null. New code cannot reconstruct its nonce
from its hash or retroactively create a proof. No ledger reset is authorized.

Alchemy's bundler fee recommendation is fetched with
`rundler_maxPriorityFeePerGas`, then buffered by 25%; latest base fee is buffered
by 50%. These are the provider's documented recommendations, not a user fee cap.
Parallel nonce lanes are supported by Alchemy (up to four pending operations for
an unstaked sender); this service permits only the original and one cancellation.
Sources: https://www.alchemy.com/docs/wallets/reference/bundler-faqs and
https://www.alchemy.com/docs/wallets/transactions/low-level-infra/bundler/overview .

## Successful viem/Alchemy Base mainnet swap, 2026-10-27

The user requested a fresh smart account after the unresolved opaque CDP swap.
The new active address is `0xD09d6F783A9840E5Ca35E134912765dc11C895A1`;
its former wallet remains archived with the original unresolved status and funds.
Address-scoped pending-operation guards isolate the new wallet without resetting
or invalidating the former wallet's signatures.

Separately confirmed deployment + exact 0.1 USDC Permit2 approval succeeded at
https://basescan.org/tx/0x49fc1a84978c59d7d9921942dba73c19868df046a5764e4c94bed9caea694e02 .
The original ETH funding was insufficient for the subsequent swap's upfront gas;
the check stopped before Permit2 signing and the user confirmed an additional
0.000005 ETH transfer. No unknown swap was retried.

The user-confirmed 0.1 USDC -> native ETH swap (1% slippage) then succeeded at
https://basescan.org/tx/0x1f4d5dc8fd24025b49b33516872fad5e94ce69d424c741c6d465aac5df8ee70f .
Its matching EntryPoint UserOperationEvent reports success, nonce 1 and gas cost
2070225000000 wei (331236 gas). Native transfer tracing independently agrees with
wallet balance + EntryPoint deposit + fee reconciliation: 42359865275888 wei ETH
received, above the confirmed minimum 41936266619701 wei. USDC balance fell from
1 to 0.9. The raw signed operation and Permit2 signature were not logged.

This validates the full deployed Base call/swap path using CDP owner signatures,
viem preparation and Alchemy submission. Ethereum execution, x402 settlement and
nonce cancellation are separate flows; this probe did not execute them. Future
previews should expose ERC-4337 gas/prefund checks before Permit2 signing; the
current generic preview's execution-only gas and swap protocol fee are insufficient
for determining total upfront ETH requirements.


## One-time replacement helper disabled, 2026-10-28

The operator replacement script and registry replacement writer are now retained
as commented reference code. The runnable script fails immediately without
loading credentials or opening network/database connections. First-wallet
creation, archived-wallet reads, additive migration 011 and per-address operation
isolation remain active for the existing replacement wallet. See README.
