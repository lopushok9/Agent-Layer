# Hosted x402 Payment MCP

A new, standalone buyer-side MCP for cloud agents. It discovers services only through CDP Bazaar and pays x402 v2 `exact`, `upto`, `batch-settlement`, and `auth-capture` requirements using canonical USDC on Base (`eip155:8453`). It never receives payments and never exposes a generic signing method.

## Identity model

This service is its own OAuth 2.1 authorization server. Google and GitHub are used only to prove the human's identity; they do not issue MCP access tokens and no external identity-platform infrastructure is required.

The stable database identity is `(provider, provider subject)`. Each identity owns one named CDP EVM account. New conversations and devices reconnect to that same wallet after OAuth. Losing a host application's connector session only requires signing in again; it does not lose the wallet. Google and GitHub identities are deliberately not auto-linked by email, so choosing a different provider creates a different wallet in this MVP.

The MCP client receives a 15-minute ES256 access token plus a rotating opaque refresh token. It never receives a CDP credential, private key, wallet secret, or signing capability.

The provider choice uses ordinary links so it works reliably in mobile and embedded browsers. After Google or GitHub verifies the user's identity, the service shows the requesting MCP client's name, return origin, and payment scope and requires an explicit one-time approval. Provider state is signed and bound to the selected provider, and an authorization code is issued only after that final approval, so a login link prepared by another client cannot silently deliver the user's grant to that client. The page immediately displays progress after a tap, and the final POST uses an explicit `303 See Other`. Its CSP permits the form redirect only to the exact registered client origin; this avoids browsers blocking the OAuth callback while retaining a narrow form destination policy. Duplicate approval submissions return the same short-lived PKCE-bound code instead of failing or minting another grant, which makes the redirect reliable in hosts that repeat form navigation.

## Payment flow

1. `x402_search` searches CDP Bazaar and returns signed, expiring `service_ref` values instead of raw payment destinations.
2. `x402_preview` verifies the resource is still in Bazaar, applies optional scalar query parameters, performs an unpaid request, selects one supported scheme, and stores a short-lived fingerprint of the exact URL, request body, and payment terms. Provider validation errors are returned with a bounded, explicitly untrusted response preview so callers can correct parameters before any payment is signed.
3. `x402_pay` atomically consumes the preview, reserves the user's rolling 24-hour limit when that optional control is enabled, repeats the request, and checks the fingerprint inside the x402 SDK hook immediately before CDP signs.

Batch-settlement channel state is stored durably in PostgreSQL, and payments are serialized per user with a PostgreSQL advisory lock so concurrent requests cannot sign conflicting cumulative vouchers. The SDK's default channel deposit is five times the advertised per-request maximum; this funds subsequent voucher-only calls and is distinct from the amount the seller may charge for the current request.

The CDP account signer is paired with the project's authenticated Base RPC for read-only allowance checks and standard gas-sponsoring extensions. This lets Permit2-based `upto` routes use seller-advertised approval sponsorship without exposing a generic transaction-signing MCP tool.

Spend limits are disabled by default. The existing 1 USDC per-payment and 5 USDC rolling-24-hour controls can be restored with `SPEND_LIMITS_ENABLED=true`; when enabled, `unknown` outcomes remain charged against the daily limit because a timeout after signing can still have settled. A preview can be consumed only once in either mode.

## Arc (basic receive and send)

The same CDP account address also works on Arc mainnet (chain id 5042), where
USDC is the gas asset.

- `arc_wallet_status` returns the receive address, the Arc USDC balance, and
  the transfer limits.
- `arc_transfer_preview` validates the recipient and amount, estimates the
  network fee (paid in USDC), and stores a single-use preview. It never signs.
- `arc_transfer` consumes that preview and sends exactly one USDC
  `transfer(to, amount)` through the USDC interface at
  `0x3600000000000000000000000000000000000000`.

CDP has no Arc network yet, so the CDP account signs the fully built EIP-1559
transaction and the service broadcasts it through `ARC_RPC_URL`. Limits are
always on: `ARC_MAX_TRANSFER_USDC_ATOMIC` (default 50 USDC) per transfer and
`ARC_MAX_DAILY_TRANSFER_USDC_ATOMIC` (default 200 USDC) per rolling 24 hours.
A transfer whose outcome cannot be confirmed after signing is recorded as
`unknown` and is never retried automatically.

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

Create a new Railway service from this directory and add a PostgreSQL service. Configure every variable from `.env.example`; `DATABASE_URL` can use the Railway Postgres reference. Set `ARC_RPC_URL` as a service secret to the Alchemy Arc Mainnet endpoint (`https://arc-mainnet.g.alchemy.com/v2/<API_KEY>`). It is required and deliberately has no public-RPC fallback. The included Dockerfile builds on Node 24, and `railway.json` runs the migration before deployment.

Generate the signing JWK locally and store it as a Railway secret. Keep the same JWK across redeploys or all current access tokens will become invalid. CDP credentials must be service-level secrets with access only to this MCP.

After deployment, give the MCP host only this URL:

```text
https://YOUR_DOMAIN/mcp
```

The host discovers OAuth metadata, dynamically registers, opens Google/GitHub login, and retains the refresh token in its connector storage. Mobile apps do not need to create or remember an environment variable.

## Production boundaries

- Apply a Railway/network egress policy as a second SSRF barrier. The code requires HTTPS, rejects credentials/custom ports, and uses DNS resolution that rejects private/link-local answers.
- Back up Postgres. CDP remains the key custodian, while the DB contains the durable user-to-CDP-account mapping and OAuth grants.
- Treat a payment timeout after signing as indeterminate and reconcile by transaction/payment audit data before allowing manual retries.
- The initial migration is intentionally small; use additive numbered migrations after the first production deployment.
