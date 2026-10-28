# Hosted Smart Wallet MCP

Managed CDP smart accounts on Ethereum and Base, with Google/GitHub login and
transaction confirmation in chat. Each user has a public smart-account receive
address and an internal CDP-managed EOA owner. The owner address is never a funding
address. This is a fresh wallet namespace: legacy wallets are preserved but are
not imported, swept, renamed or displayed as the new smart wallet.

The service exposes universal ABI/raw contract CALL batches through
`transaction_prepare` -> `transaction_execute` -> `transaction_status`.
Optional Stripe Link remains a separate approved-purchase integration.
Arc tools are removed. No passkey ceremony or autonomous session keys are included.

Base USDC x402 payments initially support **exact/EIP-3009 authorization only**.
Other schemes and SIWx are disabled for this smart-account path until compatibility
is independently established; there is no hidden owner-EOA fallback.

See [SMART_ACCOUNTS.md](SMART_ACCOUNTS.md) for design and source references.

## Universal contract workflow

Request OAuth scopes `x402:pay wallet:transact` (or only `wallet:transact`). The
consent page explicitly describes arbitrary-contract execution. Existing tokens,
refresh grants and personal access tokens retain their existing x402-only scope;
reconnect with the new scope to access contract tools.

1. `smart_wallet_status({network:"base"})` returns the receive address, native
   balance and deployment state. Ethereum uses `network:"ethereum"`.
2. `contract_read` accepts `network`, `to`, `abi`, `function_name`, and `args`.
   It never signs. Returned strings and caller-provided ABI are untrusted.
3. `transaction_prepare` accepts up to 16 ordered calls on one network. Each call
   is `{to,value,data}` or `{to,value,abi,function_name,args}`; `value` defaults to
   `"0"`. All amounts use integer atomic-unit strings. No delegatecall, self-call,
   owner-call, dynamic runtime amount or cross-chain mode is exposed.
4. The service simulates calls sequentially with the smart account as sender and
   persists a user-owned, expiring immutable preview. Show calls, values,
   allowances, simulated asset changes and warnings to the user before approval.
5. After the user's chat confirmation, call `transaction_execute` with the exact
   `operation_id` and a purpose. An invocation trusts the host to obtain consent;
   this is not an independent cryptographic proof of human confirmation.
6. Poll `transaction_status`. It verifies the matching EntryPoint UserOperation
   event rather than treating outer transaction success as execution success.
   `confirmed` means observed inclusion, not irreversible chain finality.

RPC simulation requires `eth_simulateV1` and fails closed if unavailable. It covers
sequential call effects, not account deployment/signature validation; tx.origin and deployment callbacks can differ; CDP prepares
and validates the UserOperation separately. Asset traces can be incomplete.
Successful simulation does not establish contract safety or future price.

New UserOperations are built locally with viem and sent through the configured
Alchemy bundler. CDP retains the owner keys and signs the exact operation hash.
Gas is paid from the smart account's ETH balance on both Base and Ethereum;
this executor does not request CDP sponsorship or use legacy paymaster settings.
The preview shows execution gas only, not an enforced total network fee ceiling.

`wallet_operations` binds user/network/address/calls, single-use consumption,
provider hash and idempotency ID. The hash is persisted before owner signing.
Signing/submission timeouts remain `unknown`; never automatically rebuild or resend.
An unresolved operation blocks another execution on the same user's network.
Use status reconciliation; a dropped/not-found provider response does not prove
that a signed operation can never land. A crash in reserved state without a hash
requires operator investigation; no unsafe reset tool is exposed.

Contract ABIs may come from verified registries or the caller; this first version
accepts supplied ABI and raw calldata and labels their provenance explicitly. It
does not automatically discover ABIs or certify protocol addresses.
Any protocol can be composed with fixed calls. A CDP managed-swap alternative is
available below; other intent adapters and on-chain permissions are separate extensions.

## CDP managed swap alternative

With the same `wallet:transact` scope, use `swap_preview` -> `swap_execute` ->
`transaction_status` instead of constructing router ABI/calldata. Supported networks
are Ethereum and Base mainnet; CDP Trade API does not support testnet swaps.

Example `swap_preview` input (1 USDC on Base, output WETH):

```json
{
  "network": "base",
  "from_token": "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913",
  "to_token": "0x4200000000000000000000000000000000000006",
  "from_amount_atomic": "1000000",
  "slippage_bps": 100
}
```

Use `0xEeeeeEeeeEeEeeEeEeEeeEEEeeeeEeeeeeeeEEeE` for native ETH. Slippage defaults
to 100 bps (1%) and is limited to 500 bps (5%). No custom recipient or signing
payload is accepted: the user's smart account is always the taker.

The preview uses non-binding `getSwapPrice`, not an executable quote, and shows
expected output, a fixed minimum output, estimated fees and approval requirements.
Confirm these terms in chat. The preview expires after at most five minutes.
`swap_execute` consumes it once, obtains an executable quote, validates it and
signs the bounded Permit2 authorization with the CDP owner, then submits the
explicit UserOperation through viem/Alchemy. The caller does not assemble a route.

The backend checks the quote before signing: a fresh quote must preserve the approved tokens, input, slippage
and output floor. A quote with a lower minimum is rejected before signing and
requires a new preview/confirmation. Quote creation has a deterministic idempotency key. Signed UserOperations are
never automatically rebuilt or resubmitted. This adapter trusts CDP route metadata/calldata to enforce the
quoted net output; it does not independently decode the aggregator route.

ERC-20 Permit2 approval must already exist. When missing, preview returns an exact
`approval_call` to the canonical Permit2 contract, for the input amount only.
Separately preview/confirm it through the transaction builder, wait for confirmation,
then preview the swap again. No approval or unlimited allowance is submitted
silently. Some tokens require approving zero first; use an explicitly confirmed
batch for that token's approval pattern. Native ETH needs no Permit2 approval.
The builder compares fresh simulated asset changes structurally with the persisted
preview: JSONB object-key ordering is ignored, while changed token identities,
balances, amounts and array order still stop execution before signing.

These are user-directed execution tools: the user chooses the trade parameters
and confirms the exact preview in the host. A preview-only request never approves
an allowance or a swap. Host policies and permissions still apply; publishing an
execution tool cannot guarantee that every client will invoke it. A host refusal
must be distinguished from a CDP/server failure and must not be bypassed through
another tool. This service has no browser page for executing a hosted smart-wallet
swap; `/muse` and `/tokens` manage connection tokens, not swap execution.

Before signing, the executable quote must have complete CDP simulation, no reported
balance/allowance issue, a matching network and bounded Permit2 token/amount/domain.
The price estimate is not the builder's sequential `eth_simulateV1` simulation.
Both RPCs still need to be configured for chain checks and receipt verification.

Permit2 is signed before the executable UserOperation can be prepared. Migration 008 stores
operation kind, approved swap plan and an executable-quote snapshot before that
first signature request. If a response is lost after Permit2 signing, status stays
`unknown` even without a UserOperation hash, and blocks other executions on that
network. Such a case requires operator reconciliation; it must not be retried
automatically. Normal swaps use the existing `transaction_status` and EntryPoint
event verification. Calls and swaps cannot execute through each other's tool.
For legacy operations, `transaction_status` reports the queried CDP `provider_state`, including
`signed` and the prepared-operation expiry. These do not prove onchain execution
or automatically unlock an unresolved operation. Execution failures retain only
allowlisted error categories, HTTP status and UUID correlation IDs in the ledger
and logs; raw provider messages and signatures are never copied to diagnostics.
The unsigned UserOperation (which can contain Permit2 calldata) is stored encrypted,
not returned through MCP.

## Identity model

This service is its own OAuth 2.1 authorization server. Google and GitHub are used only to prove the human's identity; they do not issue MCP access tokens and no external identity-platform infrastructure is required.

The stable database identity is `(provider, provider subject)`. Each identity owns one named CDP smart account and its internal owner EOA. New conversations and devices reconnect to that same wallet after OAuth. Losing a host application's connector session only requires signing in again; it does not lose the wallet. Google and GitHub identities are deliberately not auto-linked by email, so choosing a different provider creates a different wallet in this MVP.

The MCP client receives a 15-minute ES256 access token plus a rotating opaque refresh token. It never receives a CDP credential, private key, wallet secret, or signing capability.

The provider choice uses ordinary links so it works reliably in mobile and embedded browsers. After Google or GitHub verifies the user's identity, the service shows the requesting MCP client's name, return origin, and payment scope and requires an explicit one-time approval. Provider state is signed and bound to the selected provider, and an authorization code is issued only after that final approval, so a login link prepared by another client cannot silently deliver the user's grant to that client. The page immediately displays progress after a tap, and the final POST uses an explicit `303 See Other`. Its CSP permits the form redirect only to the exact registered client origin; this avoids browsers blocking the OAuth callback while retaining a narrow form destination policy. Duplicate approval submissions return the same short-lived PKCE-bound code instead of failing or minting another grant, which makes the redirect reliable in hosts that repeat form navigation.

## Payment flow

1. `x402_search` searches CDP Bazaar (default) or Agentic Market and returns each resource's `url`, price, and the provider's untrusted input hint.
2. `x402_preview` takes a `url`: one from search, or any public HTTPS x402 endpoint the user supplied. It reports whether the url is a Bazaar listing, detects the HTTP method (Bazaar hint, then one retry on 405), applies query parameters, caller headers and a JSON or text body, follows redirects through the SSRF guard, performs the unpaid request, selects exact/EIP-3009 authorization, and stores the request together with the provider's `PAYMENT-REQUIRED` challenge. Provider validation errors are returned with a bounded, explicitly untrusted response preview so callers can correct parameters before any payment is signed.
3. `x402_pay` atomically consumes the preview, reserves the user's rolling 24-hour limit when that optional control is enabled, signs the stored challenge, and sends one paid request. Only the amount and recipient shown in the preview can be signed. SIWx is disabled on this smart-account path; it must never sign with the owner EOA identity.

`x402_pay` returns `settled` when the provider reported a settlement, `not_charged` when access was granted without payment, and `unknown` with the provider's reason when a payment was signed but no settlement was reported. A failure before signing is an error stating that nothing was charged.

Previews last `PREVIEW_TTL_SECONDS` (default 600) and each provider request has its own `PAYMENT_TIMEOUT_MS` (default 45000) budget. Caller-supplied headers are stored only until the preview is paid or expires.

New x402 previews are bound to the smart-account payer address. Old previews from
before the wallet transition must be recreated. Batch-settlement, auth-capture,
upto and Permit2 routes are unavailable on the new smart-wallet path.

Spend limits are disabled by default. The existing 1 USDC per-payment and 5 USDC rolling-24-hour controls can be restored with `SPEND_LIMITS_ENABLED=true`; when enabled, `unknown` outcomes remain charged against the daily limit because a timeout after signing can still have settled. A preview can be consumed only once in either mode.

## Link wallet (optional)

The service can connect a user's own [Stripe Link](https://docs.stripe.com/agentic-commerce/agents/link-agent-wallet/oauth) wallet so the agent can request card and bank purchases that the user approves in Link. Link Agent Wallet serves US and Canadian customers. It is enabled when all four variables are set: `LINK_CLIENT_ID`, `LINK_CLIENT_SECRET` (issued by Stripe), `STRIPE_PUBLISHABLE_KEY` (`pk_live_…` from the Stripe dashboard, never a secret key) and `LINK_TOKEN_ENCRYPTION_KEY` (32 random bytes, base64). The redirect URI registered with Stripe must be exactly `https://YOUR_DOMAIN/auth/link/callback`.

Connecting:

1. `link_connect` returns a 10-minute `connect_url` on this domain.
2. The user signs in again with Google or GitHub. The identity must be the one the MCP session belongs to, so a link forwarded to someone else cannot attach their wallet to this account.
3. The service redirects to `login.link.com` with PKCE (S256), a random `state`, and an HttpOnly cookie that binds the callback to this browser.
4. `/auth/link/callback` consumes the single-use attempt, checks the cookie, exchanges the code with the client secret, requires the `payment_methods.agentic` scope, and stores the tokens AES-256-GCM sealed. One Link account per user; switching accounts needs `link_disconnect` first.

Access tokens refresh a minute before expiry under a per-user row lock, because Link rotates refresh tokens. Only `invalid_grant` drops a connection. `link_disconnect` revokes the grant at Link and forgets it only after Link confirms.

Purchasing:

- `link_create_spend_request` always requests approval and needs an idempotency key and a context of at least 100 characters. The user approves at `approval_url`.
- `link_get_spend_request`, `link_update_spend_request` (a new total needs new approval) and `link_cancel_spend_request` follow the request. None of them returns credentials.
- `link_get_pay_token` returns the Link Pay Token of an approved `link_pay_token` request, for Stripe checkouts that accept one. The token is bound to that merchant and amount and expires within 30 minutes.
- Card numbers are never returned. This hosted service has no browser of its own to fill a card form server-side, and putting a PAN in the agent's context would expose it in transcripts.
- `link_status` shows spend limits, verification requirements, and payment methods (brand and last four digits only). `link_shipping_addresses` lists saved addresses.

## OAuth endpoints

- `/.well-known/oauth-protected-resource/mcp`
- `/.well-known/oauth-authorization-server`
- `/oauth/register` (dynamic registration for public clients)
- `/oauth/authorize` (PKCE S256 required)
- `/oauth/token` (authorization code and rotating refresh token)
- `/oauth/revoke`
- `/oauth/jwks`
- `/mcp` (stateless Streamable HTTP)

## Personal access tokens (Meta Muse)

Hosts that store a bearer token in their own credential store instead of
finishing a browser OAuth redirect can use a personal access token. Meta
Muse is the main case: its custom connectors keep the token outside the
agent's runtime and Sentinel injects it at egress, while an OAuth redirect
back to the agent's VM forces the user to copy a code by hand.

1. Open `https://YOUR_DOMAIN/muse` (also `/tokens`) and sign in with Google or
   GitHub — the same identity reaches the same wallet as OAuth clients.
2. Create a token. It is shown once, as `alx402_…`, together with a ready
   prompt for Muse.
3. Send Muse the prompt and enter the token only in Muse's secure credential
   prompt, never in the chat.

Tokens carry the single `x402:pay` scope, expire after
`PERSONAL_TOKEN_TTL_DAYS` (default 90), are capped at
`PERSONAL_TOKEN_MAX_ACTIVE` active tokens per user (default 10), are stored
only as SHA-256 hashes, and can be revoked on the same page with immediate
effect. `/mcp` accepts both personal tokens and OAuth access tokens; the
token-manager sign-in reuses the registered Google/GitHub callbacks with a
distinct signed state type, and its pages use a short-lived form token rather
than cookies.

Set `TEST_DATABASE_URL` to run the Postgres-backed store test
(`tests/store-personal-tokens.test.ts`); it is skipped otherwise.

## Local setup

Requires Node 24 and PostgreSQL.

```bash
cp .env.example .env
npm install
npm run keys
npm run migrate
npm run dev
```

Put the one-line JWK printed by `npm run keys` into `OAUTH_SIGNING_PRIVATE_JWK`. Do not commit `.env`.

Create OAuth applications with these exact callbacks:

- Google: `https://YOUR_DOMAIN/auth/google/callback`
- GitHub: `https://YOUR_DOMAIN/auth/github/callback`

Set `PUBLIC_BASE_URL=https://YOUR_DOMAIN`. For local HTTP only, set `MCP_DANGEROUSLY_ALLOW_INSECURE_ISSUER_URL=true`; never use that setting in production.

## Railway

Create a new Railway service from this directory and add a PostgreSQL service. Configure every variable from `.env.example`; `DATABASE_URL` can use the Railway Postgres reference. Set `BASE_RPC_URL` and `ETHEREUM_RPC_URL` as service secrets to RPCs supporting eth_simulateV1. Contract reads and previews have no public-RPC fallback. The included Dockerfile builds on Node 24, and `railway.json` runs the migration before deployment.

Generate the signing JWK locally and store it as a Railway secret. Keep the same JWK across redeploys or all current access tokens will become invalid. CDP credentials must be service-level secrets with access only to this MCP.

After deployment, give the MCP host only this URL:

```text
https://YOUR_DOMAIN/mcp
```

The host discovers OAuth metadata, dynamically registers, opens Google/GitHub login, and retains the refresh token in its connector storage. Mobile apps do not need to create or remember an environment variable.

## Production boundaries

- Apply a Railway/network egress policy as a second SSRF barrier. The code requires HTTPS, rejects credentials/custom ports, and uses DNS resolution that rejects private/link-local answers. This matters more now that any public url can be previewed, including each redirect hop.
- Back up Postgres. CDP secures the owner signer keys; the DB contains smart-wallet mappings, operation attempts and OAuth grants. Server credentials can authorize spending; Google/GitHub login is not a financial signature.
- Treat a payment timeout after signing as indeterminate and reconcile by transaction/payment audit data before allowing manual retries.
- The initial migration is intentionally small; use additive numbered migrations after the first production deployment.

## Validation and rollout

Run `npm run check`, `npm test` and `npm run build`. Set `TEST_DATABASE_URL` to an
isolated PostgreSQL database for migration/replay/concurrency integration tests.
Never point test migrations at production.

Before deploying: configure RPCs, verify their chain IDs and eth_simulateV1 support,
validate CDP smart-account deployment and a bounded test transaction on each target
network, and prove exact/EIP-3009 settlement with the intended facilitator. No live
payment or production deployment is implied by passing offline tests.

Migration 007 is additive. Rollback restores the previous application version;
leave smart-wallet and operation records intact. Do not delete wallets or replay
unknown operations. Deploying this branch changes receive addresses and available
payment schemes; communicate that explicitly to connected clients.


## Explicit UserOperations and safe cancellation

Set `WALLET_OPERATION_ENCRYPTION_KEY` to a separately generated 32-byte base64
secret. Keep it in the deployment secret store and retain it for outstanding
operations; changing it without migrating ciphertext prevents reconciliation.
`BASE_BUNDLER_URL` / `ETHEREUM_BUNDLER_URL` optionally override the corresponding
RPC URLs. Alchemy endpoints must support ERC-4337 v0.6 estimation, submission and
receipt lookup in addition to execution RPC. No endpoint can be supplied via MCP.

Before any owner UserOperation signature, migration 009's encrypted ledger record
stores the full unsigned operation, nonce, EntryPoint, chain and preparation block.
The independently computed hash must match the signature and bundler response.
Normal calls and CDP-quoted swaps use nonce key 0; cancellation uses key 1. Account
factory derivation, owner index 0 and EntryPoint are checked before signing.

1. `transaction_cancel_prepare({operation_id: originalId})` creates a separate
   immutable preview of `EntryPoint.incrementNonce(0)` called by the smart account.
   It requires an unresolved original with a verified, decryptable nonce proof.
2. Show the cancellation target and gas implications. After **separate** user
   confirmation call `transaction_cancel_execute({operation_id: cancellationId,
   purpose: "..."})` once. No transfer or swap is retried.
3. Poll `transaction_status` for the cancellation. Inclusion alone does not unlock
   the original: a canonical finalized block must prove nonce advancement. Any
   independently signed Permit2 must have expired in finalized chain time too.
4. Search the entire original-to-finalized block interval for the original event.
   If it won the race, report its real confirmed/failed result; otherwise mark it
   `cancelled`. Both ledger updates commit atomically. Search failure, reorg,
   unavailable proof, pending finality or valid Permit2 retain the block.

Only one cancellation may bypass the unresolved-operation guard, and only for its
bound target. Cancellation of cancellation operations is intentionally unsupported.
A reconciliation search is capped at 100,000 blocks and fails closed beyond that;
older cases require an extended operator search, not a ledger reset.
Legacy CDP operations without raw nonce proof cannot be cancelled by these tools.
Expiry of CDP preparation or a swap quote does not substitute for nonce proof.

## One-time wallet replacement helper (disabled)

The operator script `scripts/replace-smart-wallet.ts` and the registry writer
`WalletStore.replaceWallet` are temporarily commented out after the completed
one-time replacement. Running either the source or compiled script exits with an
explicit disabled message before reading input, loading configuration, contacting
CDP or connecting to the database. No environment flag re-enables it; a reviewed
code change is required to restore the retained reference implementation.

Normal first-wallet creation remains available. Existing archived wallet records,
`walletByAddress` history reads, migration 011 and per-address pending-operation
guards remain active. They preserve the already-created wallet and its former
wallet's unresolved operation without resetting signatures or moving funds.
OAuth/PAT scopes and payer binding of existing payment previews are unchanged.
