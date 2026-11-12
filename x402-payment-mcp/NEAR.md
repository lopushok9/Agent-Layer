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
| NEAR Intents | `src/near/intents.ts` | Cross-chain swaps through 1Click. The NEAR account sells a NEAR-chain NEP-141 token (NEAR is wrapped into wNEAR automatically) in one NEAR transaction on the token contract: storage registration if needed, `near_deposit`, then `ft_transfer` to a one-time deposit address. Delivery defaults to this NEAR account (NEAR assets) or its Chain Signatures EVM address (EVM chains); refunds go to this NEAR account. The quote must echo the request exactly and name a fresh implicit deposit account. Execute refuses within 2 minutes of the deposit deadline and then submits the deposit hash. Kind `intents_swap` (migration 015) can only be executed by `intents_swap_execute`. The NEAR Intents balance (assets of any chain held for this account inside `intents.near`) is a first-class source and destination: `deliver_to: intents` credits it (e.g. SOL without a Solana address), `pay_from: intents` spends it with ONE signed NEP-413 `transfer` intent to the deposit address, published through the Solver Relay (no NEAR transaction or gas, as the near-intents.org app does; 1Click is notified with the settlement hash), and refunds return to it. Without the relay service it falls back to `mt_transfer` authorized by predecessor. `intents_balances` reads it; `intents_deposit_prepare` (`ft_transfer_call`) moves NEAR-chain tokens in, and withdrawals go out as relayed signed intents (below). EVM-origin 1Click quotes are not available yet. Optional `ONECLICK_JWT` avoids the unauthenticated 1Click fee. |
| Solver Relay (signed intents) | `src/near/solver-relay.ts` | The NEAR account signs NEP-413 messages for `intents.near` with its own key; the relay submits `execute_intents` (`publish_intents`, as the official intents SDK does) and pays the gas, so these need no NEAR in the wallet. `intents_trade_*`: best solver quote, fixed minimum, re-quote at execution, ONE message with `token_diff` and, for `deliver_to: wallet`, the withdrawal of exactly the bought amount to the wallet in the same message (atomic; NEAR arrives natively via `native_withdraw`, other NEAR-chain tokens via `ft_withdraw`, storage registration paid from intents wNEAR). `intents_swap_*` with `pay_from: intents`: the 1Click `transfer` above. `intents_withdraw_*`: ONE `native_withdraw` / `ft_withdraw` intent with no quote, which also refills wallet gas from intents wNEAR. Every message uses a versioned nonce with the current salt and a 45 s deadline, is dry-run with `simulate_intents` (only a trade may fail on the missing solver half), persisted before publishing, and reconciled by relay status or `is_nonce_used`. Kind `intents_trade` (migration 016). The relay ignores API keys today; `SOLVER_RELAY_API_KEY` is sent as Bearer if set. |
| Route selection | `src/near/solver-relay.ts` (`prepareAuto`) | `intents_exchange_prepare/execute`: one entry point for swaps from the intents balance. Asks the Solver Relay and 1Click (dry, non-binding) in parallel; takes the relay when it quotes within 0.5% of 1Click (one settlement, ~5 s), otherwise 1Click (any pair, ~20-60 s, measured 42 s for NEAR -> SOL); falls back to 1Click if the relay quote vanishes. Returns the chosen route's own preview plus `route` (chosen, why, expected_seconds, both quotes). Wallet delivery through 1Click is refused when the wallet is not registered on the token. |
| PoA bridge deposits | `src/near/poa-bridge.ts` | `intents_deposit_address` (read only): asks the PoA bridge (`deposit_address`, `supported_tokens`) for the address it assigns to THIS NEAR account on Base or Ethereum and the tokens it credits there (intents asset id, token contract, minimum). The address must be a valid EVM address for the requested chain and never this account's own Chain Signatures address. Funds are then sent with an ordinary `evm_call_prepare` from the derived address and arrive in the NEAR Intents balance, so Base ETH reaches NEAR under the same NEAR key. |
| Balances | `src/near/balances.ts` | `omni_balances` (read only): one call for everything the account holds: NEAR wallet (native NEAR, wNEAR and other NEP-141 tokens), NEAR Intents balance, and ETH plus 1Click-listed ERC-20s on the derived EVM address on Base and Ethereum (one `multicall` per chain), with USD from the cached 1Click token list and per-section and overall totals. Sources run in parallel and fail independently (`partial`, `errors`). The FastNEAR indexer only hints which FT contracts to check; every amount comes from `ft_balance_of` on NEAR RPC, and if the indexer is down the NEAR-chain tokens 1Click lists are checked. The RPC chain_id check runs once per process. |
| MCP and OAuth | `src/near/mcp.ts`, `src/oauth.ts` | 27 tools. `near:transact` is granted only for the `/near/mcp` resource and its tokens carry their own audience. |

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
