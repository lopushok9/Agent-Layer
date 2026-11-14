# API payments through the NEAR Omni Account

`POST /near/mcp` can pay x402 v2 `exact/EIP-3009` APIs with canonical USDC on
Base. The payer is the existing Chain Signatures address for the user's NEAR
account and `agentlayer-evm-1` path. Every authorization is requested through
that NEAR account's `v1.signer` call. The separate CDP EVM wallet is never used.

## Enable and authorize

Use the existing NEAR mainnet configuration and deployment-owned Base RPC:

```dotenv
NEAR_RPC_URL=https://free.rpc.fastnear.com
NEAR_NETWORK=mainnet
NEAR_SIGNER=sealed_key
NEAR_KEY_ENCRYPTION_KEY=<existing 32-byte base64 key>
BASE_RPC_URL=<deployment-owned Base mainnet HTTPS RPC>
```

Request both scopes for the `/near/mcp` OAuth resource:

```text
near:transact near:x402:pay
```

The payment permission is explicit: default and existing `near:transact` grants
keep their original tools and do not acquire payment tools. Reconnect with both
scopes to enable payments; refreshing an old grant does not add this permission.
The consent page describes the USDC payment and NEAR signing fee. `/mcp` tokens
and personal access tokens cannot authorize this resource.

Migration `018_near_x402.sql` runs with the existing startup/migration process.
It adds the encrypted payment ledger and `x402_authorization` operation kind.
Payload encryption uses `NEAR_KEY_ENCRYPTION_KEY`, falling back to
`WALLET_OPERATION_ENCRYPTION_KEY`. With a `cdp_solana` NEAR signer, configure one
of these keys explicitly. Without either key, or on NEAR testnet, NEAR payment
tools are not enabled. Preserve the encryption key across deploys and restarts.

Fund the active NEAR account for MPC gas and its derived address with Base
USDC (`0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913`). Assets on NEAR or inside
Intents must first be delivered through `omni_transfer`. The facilitator pays
the Base settlement gas; this payment requires neither Base ETH from the payer
nor an ERC-20 approval. Separate swaps and contract calls retain their gas rules.

## Tools and workflow

| Tool | Behavior |
|---|---|
| `x402_search` | Read-only Bazaar / Agentic Market discovery |
| `x402_preview` | Unpaid API probe; show exact URL, amount, recipient, derived payer and NEAR fee |
| `x402_pay` | After confirmation, consume preview once and execute its payment |
| `x402_status` | Reconcile that same payment and resume its first dispatch if MPC was pending |

Preview accepts `url`, optional `method`, `query`, `headers`, JSON `body` or
`text_body`, and `scheme: auto|exact`. Its URL must come from the user or
`x402_search`. Execution takes `preview_id` and an audit `purpose`; status takes
the same `preview_id`. Show the preview and obtain confirmation before execution.

The first version supports USDC's `USD Coin` / `2` EIP-712 domain and payment
authorization windows of 30–3600 seconds. It does not enable Permit2, SIWx,
`upto`, batch settlement, auth-capture, x402 v1 or other assets/networks.
EIP-7702 is optional; an already-delegated payer must use the pinned
Simple7702Account, pass ERC-1271 and simulate the actual USDC authorization.

## Durability and outcomes

The preview binds the HTTP request (including headers/body), NEAR identity,
derivation path, payer and payment terms. After confirmation, execution generates
one random EIP-3009 nonce and deadline, encrypts their preimage, then previews
and signs the corresponding EIP-712 digest through NEAR. The authorization
window starts at execution, so time spent reviewing the preview does not use it.
An increased NEAR fee requires another preview. MPC signatures are recovered to
the expected payer, normalized to low-S and simulated on Base before dispatch.

NEAR receives only the digest/path, never API credentials or the full
authorization. Request credentials, nonce and payment signature are encrypted
with AES-256-GCM and bound to the payment ID and user. The request is scrubbed
at the durable HTTP dispatch boundary. Generic NEAR status/activity tools do
not expose the MPC signature as a reusable payment credential.

Status can reconcile an already-broadcast NEAR request and complete the
originally approved **first** HTTP dispatch. It never requests another nonce or
signature, and never retries a dispatched HTTP request. It therefore has write
annotations. A crash after the dispatch marker can sacrifice API delivery even
if the process died just before sending: avoiding a duplicate purchase wins.

`settled` requires a successful Base receipt with matching USDC
`AuthorizationUsed` and `Transfer` logs, including payer, recipient, amount and
nonce. The API's payment-response header alone cannot prove settlement.
`resource_received` and `response_status`, when present, describe API delivery
separately: a paid API can fail, or its response can be lost.

A delegated payer can pass on-chain simulation but still be rejected by a facilitator; the preview exposes the payer account type and compatibility warning. Do not claim all providers reject delegated accounts based on a single response.

Status exposes `authorization_valid_before_unix` (seconds UTC) once an authorization exists, and sanitized `reconciliation` diagnostics for an unknown payment. The deadline passing on the wall clock alone does not release a reservation: the finalized Base block and logs must confirm it. A provider rejection or unchanged balance is not proof of non-payment.

`unknown` / `sending` retain the reservation and block a new NEAR payment.
Use `x402_status`; do not create a replacement purchase. A finalized
`AuthorizationCanceled` event means `cancelled`, not paid. Finalized Base time
past the deadline, with complete logs showing no consumption, permits `expired`.
RPC errors never release an uncertain reservation. With spend limits enabled,
the existing and NEAR payment ledgers share the rolling daily USDC budget.

## Verification

```bash
npm run check
npm test
TEST_DATABASE_URL=postgresql://... npm test
```

`near-x402.test.ts` covers real NEAR transaction encoding against a fake MPC,
EIP-712 recovery, high-S normalization, delegation, request binding, restart,
timeouts, nonce reuse prevention, expiry, receipt validation and scope gating.
`near-x402-store.test.ts` exercises PostgreSQL migrations, authenticated
encryption, ownership, concurrency and the combined budget.

These tests spend no mainnet funds. A real NEAR MPC / Base / facilitator
acceptance payment and live latency measurements remain deployment validation.
