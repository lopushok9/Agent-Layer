import express, { type Request, type Response } from "express";
import type { Config } from "./config.js";
import { asyncRoute, brand, html, oauthJsonError, pageStyles, providerAuthorizationUrl, requiredBody, requiredQuery, secureHtml, withinOAuthLimits } from "./oauth.js";
import { newPersonalToken, randomToken, TokenService } from "./security.js";
import type { PersonalToken, Store } from "./store.js";

// Personal access tokens exist for hosts such as Meta Muse whose custom
// connectors keep a bearer token in their own credential store (injected at
// egress, never shown to the agent) and cannot finish a browser OAuth
// redirect back to the agent's VM. The token carries the same single scope
// an OAuth grant does and is shown to the user exactly once.
const TOKEN_SCOPE = "x402:pay";
const MANAGER_SESSION_SECONDS = 15 * 60;

type Provider = "google" | "github";

export function tokenManagerRouter(config: Config, store: Store, tokens: TokenService) {
  const router = express.Router();

  const signIn = asyncRoute(async (req, res) => {
    if (!await withinOAuthLimits(req, store, "tokens_signin", 60, 600, 5000)) return rateLimited(res);
    const stateId = await store.createTokenLoginState();
    sendPage(res, signInPage({ stateId, google: Boolean(config.GOOGLE_CLIENT_ID), github: Boolean(config.GITHUB_CLIENT_ID) }));
  });
  router.get("/muse", signIn);
  router.get("/tokens", signIn);

  router.get("/tokens/auth/:provider/start", asyncRoute(async (req, res) => {
    const provider = req.params.provider;
    if ((provider !== "google" && provider !== "github") || !providerConfigured(config, provider)) return oauthJsonError(res, 400, "invalid_request", "identity provider is not configured");
    const stateId = requiredQuery(req, "login_state");
    if (!await store.hasTokenLoginState(stateId)) return sendPage(res, messagePage("This sign-in link has expired.", "Start again to manage your tokens."), 400);
    const state = await tokens.tokenManagerState(stateId, provider);
    res.set("Cache-Control", "no-store").redirect(providerAuthorizationUrl(provider, state, config));
  }));

  router.post("/tokens/create", express.urlencoded({ extended: false, limit: "8kb" }), asyncRoute(async (req, res) => {
    if (!await withinOAuthLimits(req, store, "tokens_write", 30, 600, 2000)) return rateLimited(res);
    const session = requiredBody(req, "manage_token");
    const userId = await store.getTokenManagerSession(session);
    if (!userId) return sessionExpired(res);
    const label = normalizeLabel(req.body?.label);
    const token = newPersonalToken();
    const created = await store.createPersonalToken(userId, token, label, TOKEN_SCOPE, config.PERSONAL_TOKEN_TTL_DAYS, config.PERSONAL_TOKEN_MAX_ACTIVE);
    if (!created) return renderManager(res, store, config, userId, session, { error: `You already have ${config.PERSONAL_TOKEN_MAX_ACTIVE} active tokens. Revoke one first.` });
    await renderManager(res, store, config, userId, session, { created: { token, record: created } });
  }));

  router.post("/tokens/revoke", express.urlencoded({ extended: false, limit: "8kb" }), asyncRoute(async (req, res) => {
    if (!await withinOAuthLimits(req, store, "tokens_write", 30, 600, 2000)) return rateLimited(res);
    const session = requiredBody(req, "manage_token");
    const userId = await store.getTokenManagerSession(session);
    if (!userId) return sessionExpired(res);
    const revoked = await store.revokePersonalToken(userId, requiredBody(req, "token_id"));
    await renderManager(res, store, config, userId, session, revoked ? { notice: "Token revoked. Connectors using it stop working immediately." } : { error: "That token was not found or is already revoked." });
  }));

  return router;
}

// Called from the shared Google/GitHub callback routes when the provider
// state is a token-manager state rather than an MCP client's login state.
export async function tokenManagerCallback(req: Request, res: Response, store: Store, tokens: TokenService, config: Config, provider: Provider, identity: () => Promise<string>) {
  const stateId = await tokens.verifyTokenManagerState(requiredQuery(req, "state"), provider);
  if (!await store.consumeTokenLoginState(stateId)) return sendPage(res, messagePage("This sign-in link has expired.", "Start again to manage your tokens."), 400);
  if (typeof req.query.error === "string") return sendPage(res, messagePage("Sign-in was not completed.", "No token was created."), 400);
  const userId = await identity();
  const session = await store.createTokenManagerSession(userId, MANAGER_SESSION_SECONDS);
  await renderManager(res, store, config, userId, session, {});
}

type ManagerState = { created?: { token: string; record: PersonalToken }; notice?: string; error?: string };

async function renderManager(res: Response, store: Store, config: Config, userId: string, session: string, state: ManagerState) {
  const active = await store.listPersonalTokens(userId);
  sendPage(res, managerPage({ session, active, state, resource: config.resource, ttlDays: config.PERSONAL_TOKEN_TTL_DAYS }), state.error ? 400 : 200);
}

export function musePrompt(resource: string) {
  return `Add a custom connector for AgentLayer x402 payments. It is a remote MCP server over streamable HTTP at ${resource} and uses bearer-token auth (Authorization: Bearer <token>), not OAuth. Ask me for the token through your secure credential prompt and never ask me to paste it into this chat. Then list its tools to confirm the connection works.`;
}

function normalizeLabel(value: unknown) {
  const text = typeof value === "string" ? value.replace(/[\u0000-\u001f\u007f]/g, "").trim().slice(0, 60) : "";
  return text || "Muse";
}
function providerConfigured(config: Config, provider: Provider) { return provider === "google" ? Boolean(config.GOOGLE_CLIENT_ID) : Boolean(config.GITHUB_CLIENT_ID); }
function sessionExpired(res: Response) { return sendPage(res, messagePage("Your session has expired.", "Sign in again to create or revoke tokens."), 401); }
function rateLimited(res: Response) { return res.status(429).set("Retry-After", "600").json({ error: "temporarily_unavailable", error_description: "too many requests" }); }
function sendPage(res: Response, page: (nonce: string) => string, status = 200) { const nonce = randomToken(16); secureHtml(res, nonce, "'self'").status(status).send(page(nonce)); }
function date(value: Date) { return value.toISOString().slice(0, 10); }

function shell(title: string, body: string, nonce: string, script = "") {
  return `<!doctype html><html><head><meta name="viewport" content="width=device-width"><meta name="color-scheme" content="light"><title>${html(title)} · AgentLayer</title><style>${pageStyles()}${EXTRA_STYLES}</style></head><body><main>${brand()}${body}${script ? `<script nonce="${nonce}">${script}</script>` : ""}</main></body></html>`;
}

function signInPage(input: { stateId: string; google: boolean; github: boolean }) {
  const q = encodeURIComponent(input.stateId);
  const links = [
    input.google ? `<a class="action secondary" href="/tokens/auth/google/start?login_state=${q}">Continue with Google</a>` : "",
    input.github ? `<a class="action secondary" href="/tokens/auth/github/start?login_state=${q}">Continue with GitHub</a>` : "",
  ].join("");
  return (nonce: string) => shell("Connect Muse", `<div class="eyebrow">Muse connector</div><h1>Connect Muse to your x402 wallet</h1><p class="intro">Sign in to create a personal access token. Muse keeps it in its secure credential store, so the agent never sees it.</p><div class="actions">${links}</div><p class="footnote">Use the same Google or GitHub account you use with AgentLayer elsewhere to reach the same wallet.</p>`, nonce);
}

function messagePage(title: string, detail: string) {
  return (nonce: string) => shell(title, `<div class="eyebrow">Muse connector</div><h1>${html(title)}</h1><p class="intro">${html(detail)}</p><div class="actions"><a class="action primary" href="/muse">Start again</a></div>`, nonce);
}

function managerPage(input: { session: string; active: PersonalToken[]; state: ManagerState; resource: string; ttlDays: number }) {
  const hidden = `<input type="hidden" name="manage_token" value="${html(input.session)}">`;
  const created = input.state.created ? `<section class="created"><h2>Copy your token now</h2><p>It is shown only once. Paste it into Muse's secure credential prompt, never into the chat.</p><div class="copy"><code id="token">${html(input.state.created.token)}</code><button class="action primary small" type="button" data-copy="token">Copy</button></div><h2>Then tell Muse</h2><div class="copy"><code id="prompt">${html(musePrompt(input.resource))}</code><button class="action secondary small" type="button" data-copy="prompt">Copy</button></div></section>` : "";
  const notice = input.state.notice ? `<p class="notice">${html(input.state.notice)}</p>` : "";
  const error = input.state.error ? `<p class="error">${html(input.state.error)}</p>` : "";
  const rows = input.active.length ? input.active.map((t) => `<li><div><strong>${html(t.label)}</strong><span>alx402_…${html(t.hint)} · expires ${date(t.expiresAt)}${t.lastUsedAt ? ` · last used ${date(t.lastUsedAt)}` : " · never used"}</span></div><form method="post" action="/tokens/revoke">${hidden}<input type="hidden" name="token_id" value="${html(t.id)}"><button class="action secondary small" type="submit">Revoke</button></form></li>`).join("") : `<li class="empty">No active tokens.</li>`;
  const body = `<div class="eyebrow">Muse connector</div><h1>Personal access tokens</h1>${notice}${error}${created}<form class="create" method="post" action="/tokens/create">${hidden}<label for="label">Name</label><input id="label" name="label" maxlength="60" placeholder="Muse" autocomplete="off"><button class="action primary" type="submit">Create token</button></form><p class="footnote">Tokens can only preview and make Base USDC x402 payments and expire after ${input.ttlDays} days. Revoke a token here to cut off a connector immediately.</p><h2>Active tokens</h2><ul class="tokens">${rows}</ul>`;
  const script = `document.querySelectorAll("button[data-copy]").forEach(function(b){b.addEventListener("click",function(){var t=document.getElementById(b.dataset.copy).textContent;navigator.clipboard.writeText(t).then(function(){b.textContent="Copied";setTimeout(function(){b.textContent="Copy";},2000);});});});`;
  return (nonce: string) => shell("Personal access tokens", body, nonce, script);
}

const EXTRA_STYLES = `h2{margin:28px 0 10px;font-size:15px;font-weight:680;letter-spacing:-.01em}.primary{background:#111;color:#fff!important;-webkit-text-fill-color:#fff;border:0}.primary:hover{background:#292929}.secondary{display:flex;background:#fff;color:#111!important;-webkit-text-fill-color:#111;border:1px solid #d6d6d1}.secondary:hover{border-color:#9b9b95;background:#fafaf8}.small{min-height:36px;width:auto;padding:7px 14px;font-size:13px}.created{margin:22px 0;padding:18px;border:1px solid #111;border-radius:12px}.created h2{margin-top:0}.created h2+p{margin:0 0 12px;color:#555550;font-size:13px}.created h2:not(:first-child){margin-top:18px}.copy{display:flex;gap:10px;align-items:flex-start}.copy code{flex:1;padding:10px;background:#f4f4f1;border-radius:8px;user-select:all}.create{display:grid;gap:8px;margin-top:22px}.create label{color:#74746e;font-size:11px;font-weight:700;letter-spacing:.08em;text-transform:uppercase}.create input{padding:12px;border:1px solid #d6d6d1;border-radius:9px;font:inherit}.tokens{list-style:none;margin:0;padding:0;border-top:1px solid #e7e7e2}.tokens li{display:flex;gap:12px;align-items:center;justify-content:space-between;padding:14px 0;border-bottom:1px solid #e7e7e2}.tokens li span{display:block;color:#74746e;font-size:12px}.tokens .empty{color:#85857f}.notice{padding:10px 12px;background:#eef6ee;border-radius:8px;font-size:13px}.error{padding:10px 12px;background:#fbeaea;border-radius:8px;font-size:13px}`;
