# Hosted x402 Payment MCP

A new, standalone buyer-side MCP for cloud agents. It discovers services only through CDP Bazaar and pays only x402 v2 `exact` requirements using canonical USDC on Base (`eip155:8453`). It never receives payments and never exposes a generic signing method.

## Identity model

This service is its own OAuth 2.1 authorization server. Google and GitHub are used only to prove the human's identity; they do not issue MCP access tokens and no external identity-platform infrastructure is required.

The stable database identity is `(provider, provider subject)`. Each identity owns one named CDP EVM account. New conversations and devices reconnect to that same wallet after OAuth. Losing a host application's connector session only requires signing in again; it does not lose the wallet. Google and GitHub identities are deliberately not auto-linked by email, so choosing a different provider creates a different wallet in this MVP.

The MCP client receives a 15-minute ES256 access token plus a rotating opaque refresh token. It never receives a CDP credential, private key, wallet secret, or signing capability.

Every authorization request shows the requesting MCP client's name, return origin, and payment scope before sign-in. Consent and the upstream OAuth callback are bound to the same short-lived browser session, so a login link prepared by another client cannot silently deliver the user's grant to that client.

## Payment flow

1. `x402_search` searches CDP Bazaar and returns signed, expiring `service_ref` values instead of raw payment destinations.
2. `x402_preview` verifies the resource is still in Bazaar, performs an unpaid request, validates Base/canonical-USDC/exact requirements, and stores a short-lived request fingerprint.
3. `x402_pay` atomically consumes the preview, reserves the user's rolling 24-hour limit, repeats the request, and checks the fingerprint inside the x402 SDK hook immediately before CDP signs.

The default limits are 1 USDC per payment and 5 USDC per rolling 24 hours. `unknown` outcomes remain charged against the daily limit because a timeout after signing can still have settled. A preview can be consumed only once.

## OAuth endpoints

- `/.well-known/oauth-protected-resource/mcp`
- `/.well-known/oauth-authorization-server`
- `/oauth/register` (dynamic registration for public clients)
- `/oauth/authorize` (PKCE S256 required)
- `/oauth/token` (authorization code and rotating refresh token)
- `/oauth/revoke`
- `/oauth/jwks`
- `/mcp` (stateless Streamable HTTP)

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

Create a new Railway service from this directory and add a PostgreSQL service. Configure every variable from `.env.example`; `DATABASE_URL` can use the Railway Postgres reference. The included Dockerfile builds on Node 24, and `railway.json` runs the migration before deployment.

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
