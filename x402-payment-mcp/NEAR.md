# NEAR Omni Account (hackathon product)

A separate MCP endpoint, `POST /near/mcp`, alongside the existing Base smart wallet (`/mcp`). It reuses login, Postgres and the deployment's EVM RPCs. It does not change the smart wallet, x402 or existing OAuth grants. Spec: [NEAR_OMNI_ACCOUNT_SPEC.md](NEAR_OMNI_ACCOUNT_SPEC.md).

## What works

| Part | Module | Notes |
|---|---|---|
| Account | `src/near/account.ts` | One NEAR implicit account per user, created on first use and activated by the first NEAR deposit. |
| Keys | `src/near/keys.ts` | `sealed_key` (AES-256-GCM, bound to the user by AAD) or `cdp_solana` (CDP ed25519). Every signature is checked locally before use. |
| Builder | `src/near/transaction.ts` | Transfer and FunctionCall actions only. No AddKey, Deploy, Stake or DeleteAccount. The exact argument bytes are bound into the preview fingerprint. |
| RPC | `src/near/rpc.ts` | Supports view calls, access keys, `send_tx` and `EXPERIMENTAL_tx_status`. Failed receipts are always reported. |
| Execution | `src/near/operations.ts` | Previews are single use and expire. Nonce, hash and signed bytes are saved before broadcast. An unknown outcome blocks new operations; status can re-send the identical bytes. |
| Chain Signatures | `src/near/chain-signatures.ts` | The EVM address comes from `v1.signer.derived_public_key`. Calls go through the smart wallet's builder (verified ABI from Sourcify/Etherscan behind proxies, decoded arguments, ERC-7730 display, approve warnings) and `eth_simulateV1` with asset tracing from the derived address. Before the MPC request, execute re-checks the nonce and re-simulates against the preview's floors. The signing payload is the hash of the exact EIP-1559 transaction, and the signature must recover to the derived address before broadcast. `evm_swap_prepare` quotes Uniswap V3 (direct pools and WETH two-hops) and builds a SwapRouter02 multicall with an on-chain minimum. With EIP-7702 (`evm_delegation_prepare`), the same address delegates to the pinned Simple7702Account (`0x4Cd2…66c9`), and `evm_batch_prepare` or a swap runs several calls atomically via `executeBatch`. Delegation takes two MPC signatures: the authorization, then the self-sent type-4 transaction. |
| NEAR Intents | `src/near/intents.ts` | Cross-chain swaps through 1Click. The NEAR account sells a NEAR-chain NEP-141 token (NEAR is wrapped into wNEAR automatically) in one NEAR transaction on the token contract: storage registration if needed, `near_deposit`, then `ft_transfer` to a one-time deposit address. Delivery defaults to this NEAR account (NEAR assets) or its Chain Signatures EVM address (EVM chains); refunds go to this NEAR account. The quote must echo the request exactly and name a fresh implicit deposit account. Execute refuses within 2 minutes of the deposit deadline and then submits the deposit hash. Kind `intents_swap` (migration 015) can only be executed by `intents_swap_execute`. The NEAR Intents balance (assets of any chain held for this account inside `intents.near`) is a first-class source and destination: `deliver_to: intents` credits it (e.g. SOL without a Solana address), `pay_from: intents` spends it with one `mt_transfer` to the deposit address, and refunds return to it. `intents.near` authorizes these calls by predecessor, so the same NEAR key signs ordinary transactions and no NEP-413 or extra keys are needed. `intents_balances` reads it; `intents_deposit_prepare` (`ft_transfer_call`) and `intents_withdraw_prepare` (`ft_withdraw`) move NEAR-chain tokens in and out. EVM-origin 1Click quotes are not available yet. Optional `ONECLICK_JWT` avoids the unauthenticated 1Click fee. |
| Solver Relay trades | `src/near/solver-relay.ts` | Swaps inside the intents balance without 1Click: `intents_trade_prepare` takes the best solver quote and fixes a minimum; `intents_trade_execute` re-quotes, signs ONE NEP-413 `token_diff` intent with the NEAR account key (versioned nonce with the current `intents.near` salt, 45 s deadline), dry-runs it with `simulate_intents`, persists it, publishes it to the relay and polls `get_status`. The relay pays the settlement gas. An expired intent with an unused nonce is reported as failed. Kind `intents_trade` (migration 016). Optional `SOLVER_RELAY_API_KEY`. |
| MCP and OAuth | `src/near/mcp.ts`, `src/oauth.ts` | 21 tools. `near:transact` is granted only for the `/near/mcp` resource and its tokens carry their own audience. |

## Enable

```bash
NEAR_RPC_URL=https://free.rpc.fastnear.com   # or a dedicated RPC
NEAR_NETWORK=mainnet
NEAR_SIGNER=sealed_key
NEAR_KEY_ENCRYPTION_KEY=$(node -e "console.log(require('crypto').randomBytes(32).toString('base64'))")
```

MCP client URL: `${PUBLIC_BASE_URL}/near/mcp`. OAuth discovery: `/.well-known/oauth-protected-resource/near/mcp`.

## Verify

```bash
npm test && npm run check                                    # unit tests; set TEST_DATABASE_URL to include Postgres tests
npx tsx scripts/near-smoke-readonly.ts                       # live mainnet reads, no keys or funds
CDP_API_KEY_ID=… CDP_API_KEY_SECRET=… CDP_WALLET_SECRET=… \
  npx tsx scripts/near-probe-cdp-signer.ts                   # can CDP sign raw NEAR digests?
```

## Not done yet (by spec)

- Aurora account + XCC, NEAR Intents / 1Click swap and Earn, HOT Bridge.
- An end-to-end mainnet run with real funds (NEAR transfer, then a Chain Signatures call on Base).
