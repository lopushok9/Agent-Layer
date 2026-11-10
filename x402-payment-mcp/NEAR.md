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
| Chain Signatures | `src/near/chain-signatures.ts` | The EVM address comes from `v1.signer.derived_public_key`. The signing payload is the hash of the exact EIP-1559 transaction. The MPC signature must recover to the derived address before broadcast on Base or Ethereum. |
| MCP and OAuth | `src/near/mcp.ts`, `src/oauth.ts` | 9 tools. `near:transact` is granted only for the `/near/mcp` resource and its tokens carry their own audience. |

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
