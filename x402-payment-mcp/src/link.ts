import { createCipheriv, createDecipheriv, randomBytes } from "node:crypto";
import express, { type Request, type Response } from "express";
import { getDuplicateSpendRequest, Link, LinkApiError } from "@stripe/link-sdk";
import { z } from "zod";
import type { Config, LinkConfig } from "./config.js";
import { asyncRoute, brand, html, oauthJsonError, pageStyles, providerAuthorizationUrl, requiredQuery, secureHtml, withinOAuthLimits } from "./oauth.js";
import { pkceChallenge, randomToken, safeEqual, sha256, type TokenService } from "./security.js";
import type { LinkConnection, Store } from "./store.js";

// Link Agent Wallet (https://docs.stripe.com/agentic-commerce/agents/link-agent-wallet/oauth).
// This service is the confidential OAuth client: the client secret, the
// rotating refresh token and the PKCE verifier never leave the server, and
// stored tokens are encrypted with LINK_TOKEN_ENCRYPTION_KEY. The agent can
// create spend requests and read their status; the customer approves every
// purchase in Link. Card numbers are never returned to the agent.

const LINK_AUTHORIZE_URL = "https://login.link.com/auth";
const LINK_TOKEN_URL = "https://login.link.com/auth/token";
const LINK_REVOKE_URL = "https://login.link.com/auth/revoke";
export const LINK_SCOPES = ["payment_methods.agentic", "userinfo:read"] as const;
const PAYMENT_SCOPE = "payment_methods.agentic";
export const LINK_CALLBACK_PATH = "/auth/link/callback";
// Link codes and our connect links both live ten minutes.
const ATTEMPT_TTL_SECONDS = 600;
// Refresh ahead of expiry instead of waiting for a 401, as Link recommends.
const REFRESH_MARGIN_MS = 60_000;
const LINK_TIMEOUT_MS = 15_000;

type Provider = "google" | "github";
type LinkStore = Pick<Store, "createLinkAttempt" | "getLinkAttempt" | "startLinkAttempt" | "consumeLinkAttempt" | "getLinkConnection" | "withLinkConnection" | "recordLinkSpendRequest">;

// @stripe/link-sdk 0.13.0 ships declarations that still use its internal "@/"
// path aliases, so its resource types resolve to {} here. This is the subset
// of the SDK this service uses, typed from the SDK source.
export type LineItem = { name: string; quantity?: number | undefined; unit_amount?: number | undefined; description?: string | undefined; sku?: string | undefined; url?: string | undefined; image_url?: string | undefined; product_url?: string | undefined };
export type Total = { type: string; display_text: string; amount: number };
type NextAction = { type: string; resolution: string; display_message?: string; action_url?: string | null; expires_at?: string | null };
export type SpendRequest = {
  id: string; status: string; credential_type?: string; amount?: number; currency?: string; merchant_name?: string; merchant_url?: string;
  approval_url?: string; activity_url?: string; expires_at?: number; card_brand?: string; card_last4?: string; link_pay_token?: string;
  status_details?: { requires_action?: { next_action?: NextAction } } | null;
  payment_status_details?: { outcome?: string; code?: string | null; decline_code?: string | null } | null;
};
type PaymentMethod = { id: string; type: string; is_default: boolean; name: string; nickname?: string; card_details?: { brand: string; last4: string; exp_month: number; exp_year: number } | null; bank_account_details?: { last4: string; bank_name?: string | null } | null };
type UserInfo = { id?: string; email?: string | null; default_spend_request_currency?: string; agent_wallet_spend_limits?: unknown; agent_wallet_verification_requirement?: unknown };
export type LinkClient = {
  userInfo: { retrieve(): Promise<UserInfo> };
  paymentMethods: { list(): Promise<PaymentMethod[]> };
  shippingAddresses: { list(): Promise<unknown[]> };
  spendRequests: {
    create(params: Record<string, unknown>): Promise<SpendRequest>;
    retrieve(id: string, opts?: { include?: string[] }): Promise<SpendRequest | null>;
    update(id: string, params: Record<string, unknown>): Promise<SpendRequest>;
    requestApproval(id: string): Promise<{ id: string; approval_url: string }>;
    cancel(id: string): Promise<SpendRequest>;
  };
};
type LinkClientFactory = (options: { accessToken: string; fetch: typeof globalThis.fetch } | { getAccessToken: (options?: { forceRefresh?: boolean }) => Promise<string>; fetch: typeof globalThis.fetch }) => LinkClient;
const sdkClient: LinkClientFactory = (options) => new Link(options as never) as unknown as LinkClient;
const duplicateOf = (e: unknown) => getDuplicateSpendRequest(e) as SpendRequest | null;

export class LinkConnectionRequiredError extends Error {
  constructor(message = "No Link wallet is connected. Call link_connect and send the user the returned connect_url.") { super(message); this.name = "LinkConnectionRequiredError"; }
}
// Shown to the person in their browser; never carries provider details.
export class LinkFlowError extends Error {
  constructor(message: string) { super(message); this.name = "LinkFlowError"; }
}
const UNAVAILABLE = "Link is temporarily unavailable. Try again shortly.";

// AES-256-GCM with a context-bound AAD, so a ciphertext copied to another row or user does not decrypt.
export function seal(key: Buffer, plaintext: string, aad: string): string {
  const iv = randomBytes(12); const cipher = createCipheriv("aes-256-gcm", key, iv); cipher.setAAD(Buffer.from(aad));
  const body = Buffer.concat([cipher.update(plaintext, "utf8"), cipher.final()]);
  return `v1.${iv.toString("base64url")}.${cipher.getAuthTag().toString("base64url")}.${body.toString("base64url")}`;
}
export function unseal(key: Buffer, sealed: string, aad: string): string {
  const [version, iv, tag, body] = sealed.split(".");
  if (version !== "v1" || !iv || !tag || body === undefined) throw new Error("unsupported sealed value");
  const decipher = createDecipheriv("aes-256-gcm", key, Buffer.from(iv, "base64url")); decipher.setAAD(Buffer.from(aad)); decipher.setAuthTag(Buffer.from(tag, "base64url"));
  return Buffer.concat([decipher.update(Buffer.from(body, "base64url")), decipher.final()]).toString("utf8");
}

const TokenResponse = z.object({ access_token: z.string().min(1), refresh_token: z.string().min(1), expires_in: z.number().positive().optional(), scope: z.string().optional() });
type Tokens = { access: string; refresh: string; expiresAt: Date; scope: string };
function parseTokens(data: unknown, fallbackScope: string): Tokens {
  const t = TokenResponse.parse(data);
  // The response echoes what the customer actually granted, which can be a subset.
  return { access: t.access_token, refresh: t.refresh_token, expiresAt: new Date(Date.now() + (t.expires_in ?? 3600) * 1000), scope: normalizeScope(t.scope ?? fallbackScope) };
}
const normalizeScope = (scope: string) => scope.split(/[\s,]+/).filter(Boolean).join(" ");
const hasScope = (scope: string, wanted: string) => scope.split(" ").includes(wanted);

export type CreateSpendRequestInput = {
  credential_type: "card" | "link_pay_token";
  amount: number;
  currency: string;
  context: string;
  idempotency_key: string;
  merchant_name?: string | undefined;
  merchant_url?: string | undefined;
  merchant_account_id?: string | undefined;
  payment_method_id?: string | undefined;
  line_items?: LineItem[] | undefined;
  totals?: Total[] | undefined;
  test?: boolean | undefined;
};

export class LinkService {
  private readonly key: Buffer;
  constructor(private readonly issuer: string, private readonly link: LinkConfig, private readonly store: LinkStore, private readonly fetchImpl: typeof globalThis.fetch = globalThis.fetch, private readonly newClient: LinkClientFactory = sdkClient) { this.key = link.encryptionKey; }

  get redirectUri() { return `${this.issuer}${LINK_CALLBACK_PATH}`; }

  async attemptValid(attemptId: string) { return Boolean(await this.store.getLinkAttempt(attemptId)); }

  // MCP: link_connect. The returned page makes the user sign in again with the
  // identity this MCP session belongs to before Link is ever opened.
  async connect(userId: string, reconnect: boolean) {
    const existing = await this.store.getLinkConnection(userId);
    if (existing && !reconnect) return { connected: true, email: existing.email, granted_scope: existing.scope, next_step: "A Link wallet is already connected. Use link_status, or call link_connect with reconnect=true only if Link reported the connection as broken." };
    const attempt = await this.store.createLinkAttempt(userId, ATTEMPT_TTL_SECONDS);
    return {
      connected: Boolean(existing),
      connect_url: `${this.issuer}/link/connect?attempt=${attempt.id}`,
      expires_at: attempt.expiresAt,
      next_step: "Send connect_url to the user as a link. They confirm their AgentLayer sign-in, then approve the connection on Link's own page. Connecting does not approve any purchase. Call link_status after they finish.",
    };
  }

  // Called after the user re-confirmed their identity. Binds the attempt to
  // fresh state, PKCE verifier and a browser cookie, and returns Link's URL.
  async begin(attemptId: string, userId: string): Promise<{ authorizeUrl: string; binding: string }> {
    const attempt = await this.store.getLinkAttempt(attemptId);
    if (!attempt) throw new LinkFlowError("This Link connection link has expired or was already used. Ask your agent for a new one.");
    if (attempt.userId !== userId) throw new LinkFlowError("You signed in with a different account than the one your agent uses. Sign in with the same Google or GitHub account, or ask your agent for a new link.");
    const verifier = randomToken(48); const state = randomToken(32); const binding = randomToken(32);
    if (!await this.store.startLinkAttempt(attemptId, userId, sha256(state), sha256(binding), seal(this.key, verifier, `link-verifier:${attemptId}`))) throw new LinkFlowError("This Link connection link has expired or was already used. Ask your agent for a new one.");
    const url = new URL(LINK_AUTHORIZE_URL);
    url.search = new URLSearchParams({ key: this.link.publishableKey, client_id: this.link.clientId, redirect_uri: this.redirectUri, response_type: "code", scope: LINK_SCOPES.join(" "), state, code_challenge: pkceChallenge(verifier), code_challenge_method: "S256" }).toString();
    return { authorizeUrl: url.toString(), binding };
  }

  // Link's redirect back to /auth/link/callback.
  async complete(input: { state: string; code?: string | undefined; error?: string | undefined; binding?: string | undefined }): Promise<{ email: string | null }> {
    const attempt = await this.store.consumeLinkAttempt(sha256(input.state));
    if (!attempt) throw new LinkFlowError("This Link connection has expired or was already completed. Ask your agent for a new link.");
    if (!input.binding || !safeEqual(sha256(input.binding), attempt.bindingHash)) throw new LinkFlowError("This Link connection was started in a different browser. Ask your agent for a new link and finish it in a single browser.");
    if (input.error) throw new LinkFlowError(input.error === "access_denied" ? "You declined the Link connection. Nothing was connected." : "Link did not complete the connection. Nothing was connected.");
    if (!input.code) throw new LinkFlowError("Link did not return an authorization code. Nothing was connected.");
    const verifier = unseal(this.key, attempt.verifierEnc, `link-verifier:${attempt.id}`);
    const res = await this.tokenRequest(LINK_TOKEN_URL, { grant_type: "authorization_code", code: input.code, redirect_uri: this.redirectUri, code_verifier: verifier }).catch(() => null);
    if (!res?.ok) throw new LinkFlowError("Link did not accept the authorization. Nothing was connected; ask your agent for a new link.");
    const tokens = parseTokens(res.data, LINK_SCOPES.join(" "));
    if (!hasScope(tokens.scope, PAYMENT_SCOPE)) {
      await this.revoke(tokens.refresh).catch(() => undefined);
      throw new LinkFlowError("Link did not grant purchase access, so nothing was connected. Approve the payment permission to let your agent request purchases.");
    }
    const profile = hasScope(tokens.scope, "userinfo:read") ? await this.profile(tokens.access).catch(() => null) : null;
    const outcome = await this.store.withLinkConnection(attempt.userId, async (current, tx) => {
      // One wallet per user. Replacing it with another Link account requires
      // disconnecting first, so the old grant is revoked deliberately.
      if (current?.linkUserId && profile?.id && current.linkUserId !== profile.id) return { conflict: true as const };
      await tx.save({ linkUserId: profile?.id ?? current?.linkUserId ?? null, email: profile?.email ?? current?.email ?? null, scope: tokens.scope, accessTokenEnc: seal(this.key, tokens.access, `link-access:${attempt.userId}`), accessExpiresAt: tokens.expiresAt, refreshTokenEnc: seal(this.key, tokens.refresh, `link-refresh:${attempt.userId}`) });
      return { conflict: false as const, previous: current };
    });
    if (outcome.conflict) {
      await this.revoke(tokens.refresh).catch(() => undefined);
      throw new LinkFlowError("A different Link account is already connected. Ask your agent to disconnect it first, then connect again.");
    }
    // Reconnecting the same account issues a new grant; end the old one.
    if (outcome.previous) await this.revokeStored(outcome.previous).catch(() => undefined);
    return { email: profile?.email ?? null };
  }

  // A valid access token for this user, refreshing it under the row lock.
  async accessToken(userId: string, forceRefresh = false): Promise<string> {
    const result = await this.store.withLinkConnection(userId, async (current, tx): Promise<{ token: string } | { error: Error }> => {
      if (!current) return { error: new LinkConnectionRequiredError() };
      let refresh: string;
      try {
        if (!forceRefresh && current.accessExpiresAt.getTime() - Date.now() > REFRESH_MARGIN_MS) return { token: unseal(this.key, current.accessTokenEnc, `link-access:${userId}`) };
        refresh = unseal(this.key, current.refreshTokenEnc, `link-refresh:${userId}`);
      } catch {
        // Undecryptable (for example after a key rotation): the grant is unusable.
        await tx.remove(); return { error: new LinkConnectionRequiredError("The stored Link connection can no longer be used. Call link_connect to connect the wallet again.") };
      }
      const res = await this.tokenRequest(LINK_TOKEN_URL, { grant_type: "refresh_token", refresh_token: refresh }).catch(() => null);
      if (!res) return { error: new Error(UNAVAILABLE) };
      if (!res.ok) {
        // Only a definitive rejection drops the connection; anything else may be transient.
        if (res.data.error === "invalid_grant") { await tx.remove(); return { error: new LinkConnectionRequiredError("The Link connection was revoked or expired. Call link_connect to connect the wallet again.") }; }
        return { error: new Error(UNAVAILABLE) };
      }
      let tokens: Tokens;
      try { tokens = parseTokens(res.data, current.scope); } catch { return { error: new Error(UNAVAILABLE) }; }
      // Refresh tokens rotate: persist the new one before anything else can fail.
      await tx.save({ linkUserId: current.linkUserId, email: current.email, scope: tokens.scope, accessTokenEnc: seal(this.key, tokens.access, `link-access:${userId}`), accessExpiresAt: tokens.expiresAt, refreshTokenEnc: seal(this.key, tokens.refresh, `link-refresh:${userId}`) });
      return { token: tokens.access };
    });
    if ("error" in result) throw result.error;
    return result.token;
  }

  // MCP: link_disconnect. Revokes the grant at Link first; if that fails the
  // connection is kept so the user is never told access ended when it did not.
  async disconnect(userId: string) {
    const result = await this.store.withLinkConnection(userId, async (current, tx) => {
      if (!current) return { disconnected: false, note: "No Link wallet was connected." };
      let refresh: string | null = null;
      try { refresh = unseal(this.key, current.refreshTokenEnc, `link-refresh:${userId}`); } catch { refresh = null; }
      if (refresh) {
        const ok = await this.revoke(refresh).then(() => true, () => false);
        if (!ok) return { error: true as const };
      }
      await tx.remove();
      return { disconnected: true, note: "Link access was revoked. Spend requests already approved in Link are not affected." };
    });
    if ("error" in result) throw new Error("Link did not confirm the revocation, so the wallet is still connected. Try again shortly.");
    return result;
  }

  // MCP: link_status. Never returns full card or bank numbers.
  async status(userId: string) {
    const connection = await this.store.getLinkConnection(userId);
    if (!connection) return { connected: false, next_step: "Call link_connect and send the user the connect_url." };
    const client = this.client(userId);
    const [info, methods] = await Promise.all([
      hasScope(connection.scope, "userinfo:read") ? linkCall(() => client.userInfo.retrieve()) : Promise.resolve(null),
      linkCall(() => client.paymentMethods.list()),
    ]);
    return {
      connected: true,
      email: info?.email ?? connection.email,
      granted_scope: connection.scope,
      connected_at: connection.createdAt,
      default_currency: info?.default_spend_request_currency ?? null,
      spend_limits: info?.agent_wallet_spend_limits ?? null,
      verification_requirement: info?.agent_wallet_verification_requirement ?? null,
      payment_methods: methods.map((m) => ({ id: m.id, type: m.type, name: m.name, nickname: m.nickname ?? null, is_default: m.is_default, card: m.card_details ? { brand: m.card_details.brand, last4: m.card_details.last4, exp_month: m.card_details.exp_month, exp_year: m.card_details.exp_year } : null, bank_account: m.bank_account_details ? { bank_name: m.bank_account_details.bank_name ?? null, last4: m.bank_account_details.last4 } : null })),
    };
  }

  async shippingAddresses(userId: string) {
    const addresses = await linkCall(() => this.client(userId).shippingAddresses.list());
    return { addresses };
  }

  async createSpendRequest(userId: string, input: CreateSpendRequestInput) {
    const client = this.client(userId);
    const params = {
      idempotency_key: input.idempotency_key,
      credential_type: input.credential_type,
      amount: input.amount,
      currency: input.currency,
      context: input.context,
      // Approval is always requested; the agent can never pre-approve.
      request_approval: true,
      ...(input.payment_method_id ? { payment_details: input.payment_method_id } : {}),
      ...(input.merchant_name ? { merchant_name: input.merchant_name } : {}),
      ...(input.merchant_url ? { merchant_url: input.merchant_url } : {}),
      ...(input.merchant_account_id ? { merchant_account_id: input.merchant_account_id } : {}),
      ...(input.line_items ? { line_items: input.line_items } : {}),
      ...(input.totals ? { totals: input.totals } : {}),
      ...(input.test ? { test: true } : {}),
    };
    let request: SpendRequest;
    try { request = await client.spendRequests.create(params); }
    catch (e) {
      // A retried idempotency key returns the request it already created.
      const duplicate = duplicateOf(e);
      if (!duplicate) throw linkError(e);
      request = duplicate;
    }
    await this.store.recordLinkSpendRequest({ id: request.id, userId, credentialType: input.credential_type, amount: input.amount, currency: input.currency, merchantName: input.merchant_name ?? null, merchantUrl: input.merchant_url ?? null, merchantAccountId: input.merchant_account_id ?? null, context: input.context, test: Boolean(input.test) });
    return { ...publicSpendRequest(request), next_step: "Send approval_url to the user as a link. Creating the request does not approve it; call link_get_spend_request until status leaves pending_approval." };
  }

  async getSpendRequest(userId: string, id: string) {
    const request = await linkCall(() => this.client(userId).spendRequests.retrieve(id));
    if (!request) throw new Error("Spend request not found in this user's Link wallet.");
    return publicSpendRequest(request);
  }

  // A new total needs a fresh approval; Link then raises the authorization.
  async updateSpendRequest(userId: string, id: string, input: { amount: number; line_items?: LineItem[] | undefined; totals?: Total[] | undefined }) {
    const client = this.client(userId);
    await linkCall(() => client.spendRequests.update(id, { amount: input.amount, ...(input.line_items ? { line_items: input.line_items } : {}), ...(input.totals ? { totals: input.totals } : {}) }));
    const approval = await linkCall(() => client.spendRequests.requestApproval(id));
    const request = await linkCall(() => client.spendRequests.retrieve(id));
    return { ...(request ? publicSpendRequest(request) : { id }), approval_url: approval.approval_url, next_step: "Send approval_url to the user. The request stays usable at its original amount if Link cannot raise it." };
  }

  async cancelSpendRequest(userId: string, id: string) {
    return publicSpendRequest(await linkCall(() => this.client(userId).spendRequests.cancel(id)));
  }

  // A Link Pay Token is bound to one Stripe merchant account and this approved
  // amount and expires within 30 minutes; it is not a card number.
  async payToken(userId: string, id: string) {
    const request = await linkCall(() => this.client(userId).spendRequests.retrieve(id, { include: ["link_pay_token"] }));
    if (!request) throw new Error("Spend request not found in this user's Link wallet.");
    if (request.credential_type !== "link_pay_token") throw new Error("This spend request does not use a Link Pay Token. Card credentials are never returned by this service.");
    if (request.status !== "approved") throw new Error(`The spend request is not approved (status: ${request.status}). Do not continue checkout.`);
    if (!request.link_pay_token) throw new Error("Link has not issued the token yet. Retrieve the spend request again in a few seconds.");
    return { id: request.id, amount: request.amount ?? null, currency: request.currency ?? null, link_pay_token: request.link_pay_token, next_step: "Put the token into the checkout's input[name=\"link_pay_token\"] on the merchant page whose data-stripe-merchant-account matched, confirm the amount, then submit. Never repeat the token in chat." };
  }

  private client(userId: string) {
    return this.newClient({ getAccessToken: (options) => this.accessToken(userId, options?.forceRefresh === true), fetch: this.linkFetch });
  }

  private readonly linkFetch: typeof globalThis.fetch = (input, init) => this.fetchImpl(input, { ...init, redirect: "error", signal: AbortSignal.timeout(LINK_TIMEOUT_MS) });

  private async profile(accessToken: string) {
    const info = await this.newClient({ accessToken, fetch: this.linkFetch }).userInfo.retrieve();
    return { id: typeof info.id === "string" && info.id ? info.id : null, email: info.email ?? null };
  }

  private async tokenRequest(url: string, params: Record<string, string>) {
    const response = await this.fetchImpl(url, {
      method: "POST", redirect: "error", signal: AbortSignal.timeout(LINK_TIMEOUT_MS),
      // Link authenticates the app by its publishable key in the header and the OAuth client by id and secret in the body.
      headers: { Authorization: `Bearer ${this.link.publishableKey}`, "Content-Type": "application/x-www-form-urlencoded", Accept: "application/json" },
      body: new URLSearchParams({ ...params, client_id: this.link.clientId, client_secret: this.link.clientSecret }),
    });
    let data: Record<string, unknown> = {};
    try { const parsed = await response.json(); if (parsed && typeof parsed === "object") data = parsed as Record<string, unknown>; } catch { /* non-JSON error page */ }
    return { ok: response.ok, status: response.status, data };
  }

  private async revoke(refreshToken: string) {
    const res = await this.tokenRequest(LINK_REVOKE_URL, { token: refreshToken, token_type_hint: "refresh_token" });
    if (!res.ok) throw new Error(`Link revocation failed (${res.status})`);
  }
  private async revokeStored(connection: LinkConnection) { await this.revoke(unseal(this.key, connection.refreshTokenEnc, `link-refresh:${connection.userId}`)); }
}

// Only the fields an agent needs to follow the purchase. Credentials are never
// requested here, and nothing else from the response is passed through.
export function publicSpendRequest(r: SpendRequest) {
  const action = r.status_details?.requires_action?.next_action;
  const payment = r.payment_status_details;
  return {
    id: r.id,
    status: r.status,
    credential_type: r.credential_type ?? "card",
    amount: r.amount ?? null,
    currency: r.currency ?? null,
    merchant_name: r.merchant_name ?? null,
    merchant_url: r.merchant_url ?? null,
    approval_url: r.approval_url ?? null,
    activity_url: r.activity_url ?? null,
    expires_at: r.expires_at ?? null,
    payment_method: r.card_brand || r.card_last4 ? { brand: r.card_brand ?? null, last4: r.card_last4 ?? null } : null,
    requires_action: action ? { type: action.type, resolution: action.resolution, display_message: action.display_message, action_url: action.action_url, expires_at: action.expires_at ?? null } : null,
    payment: payment ? { outcome: payment.outcome ?? null, code: payment.code ?? null, decline_code: payment.decline_code ?? null } : null,
  };
}

async function linkCall<T>(fn: () => Promise<T>): Promise<T> { try { return await fn(); } catch (e) { throw linkError(e); } }
// Link API messages are safe to show; transport errors and response bodies are not passed on.
function linkError(e: unknown): Error {
  if (e instanceof LinkConnectionRequiredError) return e;
  if (e instanceof LinkApiError) return new Error((e as Error).message);
  if (e instanceof Error && e.message === UNAVAILABLE) return e;
  return new Error(UNAVAILABLE);
}

// --- Browser routes -------------------------------------------------------

export function linkRouter(service: LinkService, config: Config, store: Store, tokens: TokenService) {
  const router = express.Router();
  const providers: Provider[] = [...(config.GOOGLE_CLIENT_ID ? ["google" as const] : []), ...(config.GITHUB_CLIENT_ID ? ["github" as const] : [])];

  router.get("/link/connect", asyncRoute(async (req, res) => {
    if (!await withinOAuthLimits(req, store, "link_connect", 60, 600, 5000)) return rateLimited(res);
    const attemptId = attemptParam(req);
    if (!attemptId || !await service.attemptValid(attemptId)) return sendPage(res, messagePage("This link has expired", "Ask your agent for a new Link connection link."), 400);
    sendPage(res, confirmPage(attemptId, providers));
  }));

  router.get("/link/auth/:provider/start", asyncRoute(async (req, res) => {
    const provider = req.params.provider;
    if ((provider !== "google" && provider !== "github") || !providers.includes(provider)) return oauthJsonError(res, 400, "invalid_request", "identity provider is not configured");
    const attemptId = attemptParam(req);
    if (!attemptId || !await service.attemptValid(attemptId)) return sendPage(res, messagePage("This link has expired", "Ask your agent for a new Link connection link."), 400);
    res.set("Cache-Control", "no-store").redirect(providerAuthorizationUrl(provider, await tokens.linkConnectState(attemptId, provider), config));
  }));

  router.get(LINK_CALLBACK_PATH, asyncRoute(async (req, res) => {
    if (!await withinOAuthLimits(req, store, "link_callback", 60, 600, 5000)) return rateLimited(res);
    clearBindingCookie(res, config.issuer);
    try {
      const result = await service.complete({ state: requiredQuery(req, "state"), code: stringParam(req.query.code), error: stringParam(req.query.error), binding: readCookie(req, bindingCookieName(config.issuer)) });
      sendPage(res, messagePage("Your Link wallet is connected", `${result.email ? `Connected ${result.email}. ` : ""}You can return to your agent. Every purchase still needs your approval in Link.`, "Connected"));
    } catch (e) {
      if (!(e instanceof LinkFlowError)) console.error(JSON.stringify({ level: "error", event: "link_callback_failed", message: e instanceof Error ? e.message : String(e) }));
      sendPage(res, messagePage("Link was not connected", e instanceof LinkFlowError ? e.message : "Something went wrong while connecting Link. Ask your agent for a new link."), 400);
    }
  }));
  return router;
}

// Called from the shared Google/GitHub callbacks when the provider state is a
// Link connect state: the signed-in identity must be the attempt's owner.
export async function linkConnectCallback(req: Request, res: Response, service: LinkService, tokens: TokenService, issuer: string, provider: Provider, identity: () => Promise<string>) {
  try {
    const attemptId = await tokens.verifyLinkConnectState(requiredQuery(req, "state"), provider);
    if (typeof req.query.error === "string") throw new LinkFlowError("Sign-in was not completed. Nothing was connected.");
    const { authorizeUrl, binding } = await service.begin(attemptId, await identity());
    res.cookie(bindingCookieName(issuer), binding, { httpOnly: true, secure: issuer.startsWith("https:"), sameSite: "lax", path: "/", maxAge: ATTEMPT_TTL_SECONDS * 1000 });
    res.set("Cache-Control", "no-store").redirect(303, authorizeUrl);
  } catch (e) {
    if (!(e instanceof LinkFlowError)) console.error(JSON.stringify({ level: "error", event: "link_connect_failed", message: e instanceof Error ? e.message : String(e) }));
    sendPage(res, messagePage("Link was not connected", e instanceof LinkFlowError ? e.message : "This link is invalid or has expired. Ask your agent for a new one."), 400);
  }
}

// The cookie ties Link's callback to the browser that confirmed the identity,
// so a captured Link authorization URL cannot bind someone else's wallet.
export const bindingCookieName = (issuer: string) => issuer.startsWith("https:") ? "__Host-agentlayer_link" : "agentlayer_link";
function clearBindingCookie(res: Response, issuer: string) { res.clearCookie(bindingCookieName(issuer), { httpOnly: true, secure: issuer.startsWith("https:"), sameSite: "lax", path: "/" }); }
export function readCookie(req: Request, name: string): string | undefined {
  for (const part of (req.headers.cookie ?? "").split(";")) { const i = part.indexOf("="); if (i > 0 && part.slice(0, i).trim() === name) return decodeURIComponent(part.slice(i + 1).trim()); }
  return undefined;
}
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
function attemptParam(req: Request) { const v = req.query.attempt; return typeof v === "string" && UUID.test(v) ? v : null; }
function stringParam(v: unknown) { return typeof v === "string" && v ? v : undefined; }
function rateLimited(res: Response) { return res.status(429).set("Retry-After", "600").json({ error: "temporarily_unavailable", error_description: "too many requests" }); }
function sendPage(res: Response, page: (nonce: string) => string, status = 200) { const nonce = randomToken(16); secureHtml(res, nonce, "'none'").status(status).send(page(nonce)); }
function shell(title: string, body: string) { return `<!doctype html><html><head><meta name="viewport" content="width=device-width"><meta name="color-scheme" content="light"><title>${html(title)} · AgentLayer</title><style>${pageStyles()}a.action{display:flex;color:#111!important;-webkit-text-fill-color:#111;background:#fff;border:1px solid #d6d6d1}a.action:hover{border-color:#9b9b95;background:#fafaf8}</style></head><body><main>${brand()}${body}</main></body></html>`; }
function confirmPage(attemptId: string, providers: Provider[]) {
  const q = encodeURIComponent(attemptId);
  const links = providers.map((p) => `<a class="action" href="/link/auth/${p}/start?attempt=${q}">Continue with ${p === "google" ? "Google" : "GitHub"}</a>`).join("");
  return (_nonce: string) => shell("Connect Link", `<div class="eyebrow">Link wallet</div><h1>Connect your Link wallet</h1><p class="intro">First confirm it is you: sign in with the same account your agent uses. Then Link asks you to approve the connection.</p><div class="actions">${links}</div><p class="footnote">Connecting lets your agent request purchases. Each purchase still needs your approval in Link, and card numbers are never shared with the agent.</p>`);
}
function messagePage(title: string, detail: string, eyebrow = "Link wallet") {
  return (_nonce: string) => shell(title, `<div class="eyebrow">${html(eyebrow)}</div><h1>${html(title)}</h1><p class="intro">${html(detail)}</p>`);
}
