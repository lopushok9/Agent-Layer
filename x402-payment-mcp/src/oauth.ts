import { readFile } from "node:fs/promises";
import express, { type Request, type Response } from "express";
import type { Config } from "./config.js";
import { linkConnectCallback, type LinkService } from "./link.js";
import { isLinkConnectState, isTokenManagerState, pkceChallenge, randomToken, safeEqual, TokenService } from "./security.js";
import { tokenManagerCallback } from "./token-manager.js";
import { passkeyBrowserScript, passkeyRoutes } from "./passkeys.js";
import { Store } from "./store.js";

const ALLOWED_SCOPE = "x402:pay";
const ASSETS: Record<string, string> = { "geist.woff2": "font/woff2", "nofrontend-logo.png": "image/png" };
export const SUPPORTED_SCOPES = ["x402:pay", "wallet:transact"] as const;
const BRAND_LOGO_URL = "https://www.agent-layer.tech/android-chrome-512x512.png";

export function oauthRouter(config: Config, store: Store, tokens: TokenService, link: LinkService | null = null) {
  const router = express.Router();

  router.get("/.well-known/oauth-authorization-server", (_req, res) => res.set("Access-Control-Allow-Origin","*").json({
    issuer: config.issuer,
    authorization_endpoint: `${config.issuer}/oauth/authorize`,
    token_endpoint: `${config.issuer}/oauth/token`,
    registration_endpoint: `${config.issuer}/oauth/register`,
    revocation_endpoint: `${config.issuer}/oauth/revoke`,
    jwks_uri: `${config.issuer}/oauth/jwks`,
    response_types_supported: ["code"],
    grant_types_supported: ["authorization_code", "refresh_token"],
    token_endpoint_auth_methods_supported: ["none"],
    code_challenge_methods_supported: ["S256"],
    scopes_supported: SUPPORTED_SCOPES,
  }));
  // Login page assets served from this origin (the page CSP allows no other
  // font source): Geist (SIL OFL, assets/GEIST-LICENSE.txt) and the footer logo.
  router.get("/assets/:name",asyncRoute(async(req,res)=>{
    const type=ASSETS[String(req.params.name)];if(!type)return res.status(404).end();
    const body=await readFile(new URL(`../assets/${req.params.name}`,import.meta.url));
    res.set("Cache-Control","public, max-age=604800").set("X-Content-Type-Options","nosniff").type(type).send(body);
  }));
  router.get("/.well-known/oauth-protected-resource", (_req, res) => protectedMetadata(config, res));
  router.get("/.well-known/oauth-protected-resource/mcp", (_req, res) => protectedMetadata(config, res));
  router.get("/oauth/jwks", (_req, res) => res.set("Access-Control-Allow-Origin","*").json({ keys: [tokens.publicJwk] }));

  router.post("/oauth/register", asyncRoute(async (req, res) => {
    if(!await withinOAuthLimits(req,store,"register",20,3600,500))return rateLimitError(res,3600);
    const body = req.body as Record<string, unknown>;
    if (!Array.isArray(body.redirect_uris) || body.redirect_uris.length === 0 || !body.redirect_uris.every((u) => typeof u === "string" && validRedirectUri(u))) {
      return oauthJsonError(res, 400, "invalid_redirect_uri", "redirect_uris must contain HTTPS or loopback URLs");
    }
    if (body.token_endpoint_auth_method && body.token_endpoint_auth_method !== "none") return oauthJsonError(res, 400, "invalid_client_metadata", "only public clients are supported");
    const client = await store.registerClient(typeof body.client_name === "string" ? body.client_name.slice(0, 200) : "MCP client", body.redirect_uris as string[]);
    res.status(201).json({ client_id: client.clientId, client_name: client.clientName, redirect_uris: client.redirectUris, token_endpoint_auth_method: "none", grant_types: ["authorization_code", "refresh_token"], response_types: ["code"] });
  }));

  router.get("/oauth/authorize", asyncRoute(async (req, res) => {
    if(!await withinOAuthLimits(req,store,"authorize",120,600,5000))return rateLimitError(res,600);
    let p: ReturnType<typeof authorizeParams>;
    try { p = authorizeParams(req, config); } catch (e) { return oauthJsonError(res, 400, "invalid_request", e instanceof Error ? e.message : "invalid request"); }
    const error = await validateAuthorize(p, store, config);
    if (error) return oauthJsonError(res, 400, "invalid_request", error);
    const client=await store.getClient(p.clientId);if(!client)return oauthJsonError(res,400,"invalid_request","unknown client_id");
    const stateId = await store.createLoginState({ clientId:p.clientId, redirectUri:p.redirectUri, state:p.state, codeChallenge:p.codeChallenge, resource:p.resource, scope:p.scope });
    const nonce=randomToken(16);secureHtml(res,nonce,"'self'").send(loginPage({stateId,clientName:client.clientName,google:Boolean(config.GOOGLE_CLIENT_ID),github:Boolean(config.GITHUB_CLIENT_ID),nonce}));
  }));

  router.post("/oauth/consent",express.urlencoded({extended:false,limit:"8kb"}),asyncRoute(async(req,res)=>{
    const consentToken=requiredBody(req,"consent_token");const decision=requiredBody(req,"decision");
    if(decision!=="allow"&&decision!=="deny")return oauthJsonError(res,400,"invalid_request","invalid consent decision");
    const grant=decision==="allow"?await store.approvePendingConsent(consentToken):await store.denyPendingConsent(consentToken);
    if(!grant)return oauthJsonError(res,400,"invalid_request","authorization request is invalid or expired");
    store.usage?.record({kind:"auth",name:`consent_${decision}`,userId:grant.userId,clientId:grant.clientId,ok:true});
    if(decision==="deny")return redirectOAuthError(res,grant,"access_denied","The user denied the authorization request");
    finishLogin(res,grant,consentToken);
  }));

  passkeyRoutes(router,config,store,(res,state,userId,offerPasskey)=>showConsent(res,store,config,state,userId,offerPasskey),{asyncRoute,limits:withinOAuthLimits,jsonError:oauthJsonError,errorPage:passkeyErrorPage});

  router.get("/auth/google/start", asyncRoute(async(req,res)=>startProvider(req,res,store,tokens,config,"google")));
  router.get("/auth/github/start", asyncRoute(async(req,res)=>startProvider(req,res,store,tokens,config,"github")));

  const googleConfig=config.GOOGLE_CLIENT_ID&&config.GOOGLE_CLIENT_SECRET?{id:config.GOOGLE_CLIENT_ID,secret:config.GOOGLE_CLIENT_SECRET}:null;
  if(googleConfig){
    const identity=async(req:Request)=>{
      const code = requiredQuery(req, "code");
      const token = await postForm("https://oauth2.googleapis.com/token", { code, client_id:googleConfig.id, client_secret:googleConfig.secret, redirect_uri:`${config.issuer}/auth/google/callback`, grant_type:"authorization_code" });
      const profile = await getJson("https://openidconnect.googleapis.com/v1/userinfo", String(token.access_token));
      if (typeof profile.sub !== "string") throw new Error("Google did not return a subject");
      return store.upsertIdentity("google", profile.sub, stringOrNull(profile.name), stringOrNull(profile.email));
    };
    router.get("/auth/google/callback", asyncRoute(async (req, res) => {
      if(isTokenManagerState(String(req.query.state??"")))return tokenManagerCallback(req,res,store,tokens,config,"google",()=>identity(req));
      if(link&&isLinkConnectState(String(req.query.state??"")))return linkConnectCallback(req,res,link,tokens,config.issuer,"google",()=>identity(req));
      const state = await consumeCallbackState(req, store,tokens,"google");
      if(typeof req.query.error==="string")return redirectOAuthError(res,state,providerError(req.query.error),"Google sign-in was not completed");
      await showConsent(res, store, config, state, await identity(req));
    }));
  }
  const githubConfig=config.GITHUB_CLIENT_ID&&config.GITHUB_CLIENT_SECRET?{id:config.GITHUB_CLIENT_ID,secret:config.GITHUB_CLIENT_SECRET}:null;
  if(githubConfig){
    const identity=async(req:Request)=>{
      const code = requiredQuery(req, "code");
      const token = await postForm("https://github.com/login/oauth/access_token", { code, client_id:githubConfig.id, client_secret:githubConfig.secret, redirect_uri:`${config.issuer}/auth/github/callback` });
      const profile = await getJson("https://api.github.com/user", String(token.access_token), { "User-Agent":"AgentLayer-x402-MCP", Accept:"application/vnd.github+json" });
      if (typeof profile.id !== "number" && typeof profile.id !== "string") throw new Error("GitHub did not return a subject");
      return store.upsertIdentity("github", String(profile.id), stringOrNull(profile.name ?? profile.login), stringOrNull(profile.email));
    };
    router.get("/auth/github/callback", asyncRoute(async (req, res) => {
      if(isTokenManagerState(String(req.query.state??"")))return tokenManagerCallback(req,res,store,tokens,config,"github",()=>identity(req));
      if(link&&isLinkConnectState(String(req.query.state??"")))return linkConnectCallback(req,res,link,tokens,config.issuer,"github",()=>identity(req));
      const state = await consumeCallbackState(req, store,tokens,"github");
      if(typeof req.query.error==="string")return redirectOAuthError(res,state,providerError(req.query.error),"GitHub sign-in was not completed");
      await showConsent(res, store, config, state, await identity(req));
    }));
  }

  router.post("/oauth/token", express.urlencoded({ extended:false }), asyncRoute(async (req, res) => {
    res.set("Cache-Control", "no-store"); res.set("Pragma", "no-cache");
    const body=req.body as Record<string,string>;
    const client=body.client_id ? await store.getClient(body.client_id) : null;
    if(!client) return oauthJsonError(res,401,"invalid_client","unknown client_id");
    if(body.grant_type==="authorization_code"){
      if(!body.code||!body.redirect_uri||!body.code_verifier) return oauthJsonError(res,400,"invalid_request","code, redirect_uri and code_verifier are required");
      const grant=await store.consumeAuthorizationCode(body.code);
      if(!grant||grant.clientId!==client.clientId||grant.redirectUri!==body.redirect_uri||!safeEqual(pkceChallenge(body.code_verifier),grant.codeChallenge)) return oauthJsonError(res,400,"invalid_grant","invalid or expired authorization code");
      const scopes=grant.scope.split(" "); const access=await tokens.accessToken(grant.userId,client.clientId,scopes); const refresh=await store.createRefreshToken(grant.userId,client.clientId,grant.scope,config.REFRESH_TOKEN_TTL_SECONDS);
      return res.json({access_token:access,token_type:"Bearer",expires_in:config.ACCESS_TOKEN_TTL_SECONDS,refresh_token:refresh,scope:grant.scope});
    }
    if(body.grant_type==="refresh_token"){
      if(!body.refresh_token)return oauthJsonError(res,400,"invalid_request","refresh_token is required");
      const grant=await store.rotateRefreshToken(body.refresh_token,client.clientId,config.REFRESH_TOKEN_TTL_SECONDS);
      if(!grant)return oauthJsonError(res,400,"invalid_grant","invalid or expired refresh token");
      const access=await tokens.accessToken(grant.userId,client.clientId,grant.scope.split(" "));
      return res.json({access_token:access,token_type:"Bearer",expires_in:config.ACCESS_TOKEN_TTL_SECONDS,refresh_token:grant.token,scope:grant.scope});
    }
    return oauthJsonError(res,400,"unsupported_grant_type","unsupported grant_type");
  }));
  router.post("/oauth/revoke", express.urlencoded({extended:false}), asyncRoute(async(req,res)=>{if(typeof req.body.token==="string")await store.revokeRefreshToken(req.body.token);res.status(200).end();}));
  return router;
}

function protectedMetadata(config:Config,res:Response){res.set("Access-Control-Allow-Origin","*").json({resource:config.resource,authorization_servers:[config.issuer],scopes_supported:SUPPORTED_SCOPES,bearer_methods_supported:["header"]});}
// RFC 8707 makes `resource` optional and some hosts (e.g. Muse) omit it. This
// server protects a single resource, so an absent value means that resource; a
// present one must still match it exactly (validateAuthorize).
function authorizeParams(req:Request,config:Config){return{clientId:requiredQuery(req,"client_id"),redirectUri:requiredQuery(req,"redirect_uri"),state:requiredQuery(req,"state"),codeChallenge:requiredQuery(req,"code_challenge"),resource:typeof req.query.resource==="string"&&req.query.resource?req.query.resource:config.resource,responseType:requiredQuery(req,"response_type"),challengeMethod:requiredQuery(req,"code_challenge_method"),scope:typeof req.query.scope==="string"?req.query.scope:ALLOWED_SCOPE};}
async function validateAuthorize(p:ReturnType<typeof authorizeParams>,store:Store,config:Config){const c=await store.getClient(p.clientId);if(!c)return"unknown client_id";if(!c.redirectUris.includes(p.redirectUri))return"redirect_uri is not registered";if(p.responseType!=="code")return"only response_type=code is supported";if(p.challengeMethod!=="S256"||p.codeChallenge.length<43)return"PKCE S256 is required";if(p.resource!==config.resource)return"resource must identify this MCP server";if(!p.scope||p.scope.split(" ").some(s=>!(SUPPORTED_SCOPES as readonly string[]).includes(s)))return"unsupported scope";return null;}
async function startProvider(req:Request,res:Response,store:Store,tokens:TokenService,config:Config,provider:"google"|"github"){
  if((provider==="google"&&!config.GOOGLE_CLIENT_ID)||(provider==="github"&&!config.GITHUB_CLIENT_ID))return oauthJsonError(res,400,"invalid_request","identity provider is not configured");
  const stateId=requiredQuery(req,"login_state");
  if(!await store.hasLoginState(stateId))return oauthJsonError(res,400,"invalid_request","authorization request is invalid or expired");
  const providerState=await tokens.providerState(stateId,provider);
  return res.set("Cache-Control","no-store").redirect(providerAuthorizationUrl(provider,providerState,config));
}
async function consumeCallbackState(req:Request,store:Store,tokens:TokenService,provider:"google"|"github"){
  const providerState=requiredQuery(req,"state");const stateId=await tokens.verifyProviderState(providerState,provider);const row=await store.consumeLoginState(stateId);if(!row)throw new Error("invalid or expired login state");return row;
}
async function showConsent(res:Response,store:Store,config:Config,state:Awaited<ReturnType<typeof consumeCallbackState>>,userId:string,offerPasskey=true){
  const client=await store.getClient(state.clientId);if(!client)throw new Error("OAuth client no longer exists");
  const consentToken=await store.createPendingConsent(state,userId,config.AUTH_CODE_TTL_SECONDS);
  const redirectOrigin=new URL(state.redirectUri).origin;const nonce=randomToken(16);secureHtml(res,nonce,`'self' ${redirectOrigin}`).send(consentPage({consentToken,clientName:client.clientName,redirectOrigin,nonce,scope:state.scope,offerPasskey}));
}
function finishLogin(res:Response,grant:import("./store.js").AuthorizationCode,code:string){const redirect=new URL(grant.redirectUri);redirect.searchParams.set("code",code);redirect.searchParams.set("state",grant.state);res.set("Cache-Control","no-store").redirect(303,redirect.toString());}
function redirectOAuthError(res:Response,state:{redirectUri:string;state:string},error:string,description:string){const redirect=new URL(state.redirectUri);redirect.searchParams.set("error",error);redirect.searchParams.set("error_description",description);redirect.searchParams.set("state",state.state);return res.set("Cache-Control","no-store").redirect(303,redirect.toString());}
async function postForm(url:string,body:Record<string,string>){const r=await fetch(url,{method:"POST",headers:{Accept:"application/json","Content-Type":"application/x-www-form-urlencoded"},body:new URLSearchParams(body),signal:AbortSignal.timeout(10000)});if(!r.ok)throw new Error(`OAuth provider token exchange failed (${r.status})`);return r.json() as Promise<Record<string,unknown>>;}
async function getJson(url:string,token:string,headers:Record<string,string>={}){const r=await fetch(url,{headers:{...headers,Authorization:`Bearer ${token}`},signal:AbortSignal.timeout(10000)});if(!r.ok)throw new Error(`OAuth provider profile request failed (${r.status})`);return r.json() as Promise<Record<string,unknown>>;}
export function requiredQuery(req:Request,name:string){const v=req.query[name];if(typeof v!=="string"||!v)throw new Error(`missing ${name}`);return v;}
export function requiredBody(req:Request,name:string){const v=req.body?.[name];if(typeof v!=="string"||!v)throw new Error(`missing ${name}`);return v;}
function validRedirectUri(value:string){try{const u=new URL(value);return u.protocol==="https:"||(u.protocol==="http:"&&["localhost","127.0.0.1","::1"].includes(u.hostname));}catch{return false;}}
function stringOrNull(v:unknown){return typeof v==="string"?v:null;}
export function oauthJsonError(res:Response,status:number,error:string,description:string){return res.status(status).json({error,error_description:description});}
export async function withinOAuthLimits(req:Request,store:Store,bucket:string,perIp:number,windowSeconds:number,global:number){const ip=pkceChallenge(req.ip||req.socket.remoteAddress||"unknown");const [ipAllowed,globalAllowed]=await Promise.all([store.consumeRateLimit(`oauth_${bucket}_ip`,ip,perIp,windowSeconds),store.consumeRateLimit(`oauth_${bucket}_global`,"global",global,windowSeconds)]);return ipAllowed&&globalAllowed;}
function rateLimitError(res:Response,retryAfter:number){return res.status(429).set("Retry-After",String(retryAfter)).json({error:"temporarily_unavailable",error_description:"too many OAuth requests"});}
export function asyncRoute(fn:(req:Request,res:Response)=>Promise<unknown>){return(req:Request,res:Response,next:express.NextFunction)=>{Promise.resolve(fn(req,res)).catch(next);};}
export function providerAuthorizationUrl(provider:"google"|"github",state:string,config:Config){if(provider==="google"){const url=new URL("https://accounts.google.com/o/oauth2/v2/auth");url.search=new URLSearchParams({client_id:config.GOOGLE_CLIENT_ID!,redirect_uri:`${config.issuer}/auth/google/callback`,response_type:"code",scope:"openid email profile",state,prompt:"select_account"}).toString();return url.toString();}const url=new URL("https://github.com/login/oauth/authorize");url.search=new URLSearchParams({client_id:config.GITHUB_CLIENT_ID!,redirect_uri:`${config.issuer}/auth/github/callback`,scope:"read:user user:email",state}).toString();return url.toString();}
export function secureHtml(res:Response,nonce:string,formAction:string){return res.set("Cache-Control","no-store").set("Content-Security-Policy",`default-src 'none'; connect-src 'self'; img-src https://www.agent-layer.tech 'self'; font-src 'self'; style-src 'unsafe-inline'; script-src 'nonce-${nonce}'; form-action ${formAction}; frame-ancestors 'none'; base-uri 'none'`).set("X-Frame-Options","DENY").set("Referrer-Policy","no-referrer").type("html");}
function providerError(value:string){return value==="access_denied"?"access_denied":"temporarily_unavailable";}
export function html(value:string){return value.replaceAll("&","&amp;").replaceAll("<","&lt;").replaceAll(">","&gt;").replaceAll('"',"&quot;").replaceAll("'","&#39;");}
const KEY_ICON=`<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="7.5" cy="15.5" r="4.5"/><path d="M10.7 12.3 20 3"/><path d="m15.5 7.5 3 3"/><path d="m18 5 2 2"/></svg>`;
const GOOGLE_ICON=`<svg viewBox="0 0 48 48" width="18" height="18" aria-hidden="true"><path fill="#FFC107" d="M43.6 20.5H42V20H24v8h11.3C33.7 32.7 29.2 36 24 36c-6.6 0-12-5.4-12-12s5.4-12 12-12c3.1 0 5.8 1.2 7.9 3l5.7-5.7C34 6.1 29.3 4 24 4 12.9 4 4 12.9 4 24s8.9 20 20 20 20-8.9 20-20c0-1.3-.1-2.4-.4-3.5z"/><path fill="#FF3D00" d="m6.3 14.7 6.6 4.8C14.7 15.1 19 12 24 12c3.1 0 5.8 1.2 7.9 3l5.7-5.7C34 6.1 29.3 4 24 4 16.3 4 9.7 8.3 6.3 14.7z"/><path fill="#4CAF50" d="M24 44c5.2 0 9.9-2 13.4-5.2l-6.2-5.2C29.2 35.1 26.7 36 24 36c-5.2 0-9.6-3.3-11.3-8l-6.5 5C9.5 39.6 16.2 44 24 44z"/><path fill="#1976D2" d="M43.6 20.5H42V20H24v8h11.3c-.8 2.2-2.2 4.2-4.1 5.6l6.2 5.2C37 39.2 44 34 44 24c0-1.3-.1-2.4-.4-3.5z"/></svg>`;
const GITHUB_ICON=`<svg viewBox="0 0 16 16" width="18" height="18" fill="currentColor" aria-hidden="true"><path d="M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82.64-.18 1.32-.27 2-.27.68 0 1.36.09 2 .27 1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.01 8.01 0 0 0 16 8c0-4.42-3.58-8-8-8z"/></svg>`;
function loginPage(input:{stateId:string;clientName:string;google:boolean;github:boolean;nonce:string}){
  const state=encodeURIComponent(input.stateId);
  const providers=[input.google?`<a class="action" data-provider="Google" href="/auth/google/start?login_state=${state}">${GOOGLE_ICON}Continue with Google</a>`:"",input.github?`<a class="action" data-provider="GitHub" href="/auth/github/start?login_state=${state}">${GITHUB_ICON}Continue with GitHub</a>`:""].join("");
  return `<!doctype html><html lang="en"><head><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="color-scheme" content="light"><title>Sign in · AgentLayer</title><style>${pageStyles()}</style></head><body><main>${brand()}<h1>Sign in</h1><p class="intro">to continue to <strong>${html(input.clientName)}</strong></p><div class="actions"><button class="action primary" type="button" data-passkey="login">${KEY_ICON}Sign in with a passkey</button></div><p class="hint">Face ID, Touch ID or your device PIN</p>${providers?`<div class="divider">or</div><div class="actions">${providers}</div>`:""}<button class="linkish" type="button" data-passkey="register">Create an account with a passkey</button><form id="passkey-form" method="post" action="/auth/passkey/finish" hidden><input type="hidden" name="purpose"><input type="hidden" name="challenge_id"><input type="hidden" name="credential"></form><p class="status" id="status" role="status" aria-live="polite"></p><p class="footnote">Already use Google or GitHub here? Sign in with it and add a passkey on the next screen.</p><script nonce="${input.nonce}">${passkeyBrowserScript()}
var status=document.getElementById("status"),form=document.getElementById("passkey-form");
document.querySelectorAll("a[data-provider]").forEach(function(link){link.addEventListener("click",function(){link.classList.add("busy");status.textContent="Opening "+link.dataset.provider+"…";});});
document.querySelectorAll("button[data-passkey]").forEach(function(button){button.addEventListener("click",async function(){var mode=button.dataset.passkey;button.classList.add("busy");status.textContent="Waiting for your passkey…";try{var r=await passkey({mode:mode,login_state:${JSON.stringify(input.stateId)}});form.purpose.value=mode;form.challenge_id.value=r.challenge_id;form.credential.value=r.credential;status.textContent="Verifying…";form.submit();}catch(e){status.textContent=passkeyError(e);button.classList.remove("busy");}});});</script></main></body></html>`;
}
function consentPage(input:{consentToken:string;clientName:string;redirectOrigin:string;nonce:string;scope?:string;offerPasskey?:boolean}){
  return `<!doctype html><html><head><meta name="viewport" content="width=device-width"><meta name="color-scheme" content="light"><title>Authorize · AgentLayer</title><style>${pageStyles()}</style></head><body><main>${brand()}<div class="eyebrow">Authorization request</div><h1>Allow wallet access?</h1><p class="intro"><strong>${html(input.clientName)}</strong> wants to use your AgentLayer x402 wallet.</p><dl><div><dt>Returns to</dt><dd><code>${html(input.redirectOrigin)}</code></dd></div><div><dt>Permission</dt><dd>${(input.scope??"x402:pay").split(" ").includes("wallet:transact")?"Prepare and execute arbitrary smart-contract calls and ETH/token transfers on Ethereum and Base after confirmation in chat. These operations can spend wallet assets and ETH gas. ":""}${(input.scope??"x402:pay").split(" ").includes("x402:pay")?"Preview and make Base USDC x402 payments. If you connect Link, request purchases approved in Link.":""}</dd></div></dl><form class="actions" id="consent-form" method="post" action="/oauth/consent"><input type="hidden" name="consent_token" value="${html(input.consentToken)}"><button class="action allow" type="submit" name="decision" value="allow">Allow access</button><button class="action deny" type="submit" name="decision" value="deny">Cancel</button></form><p class="status" id="status" role="status" aria-live="polite"></p><p class="footnote">Continue only if you recognize this client and return address.</p>${input.offerPasskey?`<div class="passkey-offer"><button class="action" type="button" id="passkey-add">Add a passkey for next sign-in</button><p class="footnote" id="passkey-status" role="status" aria-live="polite">Next time, sign in with Face ID or a fingerprint instead of this provider. Keep this sign-in method too, to recover access if you lose your devices.</p></div>`:""}<script nonce="${input.nonce}">${input.offerPasskey?`${passkeyBrowserScript()}
var addButton=document.getElementById("passkey-add"),addStatus=document.getElementById("passkey-status");addButton.addEventListener("click",async function(){addButton.classList.add("busy");addStatus.textContent="Waiting for your passkey…";try{var token=${JSON.stringify(input.consentToken)},r=await passkey({mode:"add",consent_token:token}),s=await fetch("/auth/passkey/add",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({challenge_id:r.challenge_id,consent_token:token,credential:JSON.parse(r.credential)})}),j=await s.json();if(!s.ok)throw new Error(j.error_description||"The passkey could not be saved.");addButton.remove();addStatus.textContent=j.backed_up?"Passkey saved and synced. Next time choose “Sign in with a passkey”.":"Passkey saved on this device only. Next time choose “Sign in with a passkey”.";}catch(e){addStatus.textContent=passkeyError(e);addButton.classList.remove("busy");}});
`:""}var form=document.getElementById("consent-form"),status=document.getElementById("status");form.addEventListener("submit",function(event){if(form.dataset.submitted==="true"){event.preventDefault();return;}form.dataset.submitted="true";form.classList.add("busy");status.classList.add("busy");status.textContent=event.submitter&&event.submitter.value==="deny"?"Cancelling…":"Connecting to the MCP client…";setTimeout(function(){status.textContent="Still working — keep this window open…";},8000);});</script></main></body></html>`;
}
function passkeyErrorPage(res:Response,message:string){const nonce=randomToken(16);secureHtml(res.status(400),nonce,"'none'").send(`<!doctype html><html><head><meta name="viewport" content="width=device-width"><meta name="color-scheme" content="light"><title>Passkey · AgentLayer</title><style>${pageStyles()}</style></head><body><main>${brand()}<div class="eyebrow">Passkey</div><h1>Sign-in did not complete</h1><p class="intro">${html(message)}</p><p class="footnote">Nothing was authorized.</p></main></body></html>`);}
export function brand(){return `<header class="brand"><img src="${BRAND_LOGO_URL}" alt=""><span>AgentLayer</span></header><footer class="made"><img src="/assets/nofrontend-logo.png" alt="nofrontend" width="44" height="34"></footer>`;}
export function pageStyles(){return `@font-face{font-family:Geist;src:url(/assets/geist.woff2) format("woff2");font-weight:100 900;font-display:swap}*{box-sizing:border-box}html{background:#fafaf9}body{position:relative;min-height:100vh;min-height:100dvh;margin:0;padding:96px 24px 120px;display:grid;place-items:center;color:#0a0a0a;background:#fafaf9;font-family:Geist,ui-sans-serif,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;font-size:15px;line-height:1.5;-webkit-font-smoothing:antialiased;text-rendering:optimizeLegibility}main{width:min(100%,380px)}.brand{position:absolute;top:22px;left:24px;display:flex;align-items:center;gap:9px;color:#0a0a0a;font-size:15px;font-weight:600;letter-spacing:-.01em}.brand img{display:block;width:26px;height:26px;object-fit:contain}.made{position:absolute;left:0;right:0;bottom:24px;display:flex;justify-content:center}.made img{display:block;width:44px;height:auto}.eyebrow{margin:0 0 10px;color:#737373;font-size:13px;font-weight:500}h1{margin:0;color:#0a0a0a;font-size:28px;line-height:1.15;font-weight:600;letter-spacing:-.03em}.intro{margin:8px 0 28px;color:#737373}.intro strong{color:#0a0a0a;font-weight:500}.actions{display:grid;gap:10px;margin:0}.action{display:flex;gap:10px;min-height:48px;width:100%;align-items:center;justify-content:center;padding:12px 16px;border:1px solid #e5e5e5;border-radius:12px;background:#fff;color:#0a0a0a!important;-webkit-text-fill-color:currentColor;font:inherit;font-weight:500;text-align:center;text-decoration:none;cursor:pointer;touch-action:manipulation;transition:background .15s,border-color .15s,opacity .15s}.action:hover{border-color:#d4d4d4;background:#f5f5f5}.action svg{flex:none}.primary,.allow{border-color:#0a0a0a;background:#0a0a0a;color:#fff!important}.primary:hover,.allow:hover{border-color:#262626;background:#262626}.busy,form.busy button{pointer-events:none;opacity:.55}.divider{display:flex;align-items:center;gap:12px;margin:22px 0;color:#a3a3a3;font-size:12px}.divider:before,.divider:after{content:"";flex:1;height:1px;background:#e5e5e5}.hint{margin:10px 0 0;color:#a3a3a3;font-size:12.5px;text-align:center}.linkish{display:block;margin:22px auto 0;padding:4px;border:0;background:none;color:#525252;font:inherit;font-size:13.5px;cursor:pointer;text-decoration:underline;text-decoration-color:#d4d4d4;text-underline-offset:3px}.linkish:hover{color:#0a0a0a;text-decoration-color:currentColor}dl{margin:0 0 28px;border-top:1px solid #e5e5e5}dl div{padding:14px 0;border-bottom:1px solid #e5e5e5}dt{margin-bottom:4px;color:#737373;font-size:12px;font-weight:500}dd{margin:0;color:#262626;font-size:14px}code{font-family:ui-monospace,"SFMono-Regular",Menlo,Consolas,monospace;font-size:12.5px;overflow-wrap:anywhere}.status{min-height:20px;margin:14px 0 0;color:#525252;font-size:13px;text-align:center}.status:empty{display:none}.status.busy:before{content:"";display:inline-block;width:12px;height:12px;margin-right:8px;vertical-align:-1px;border:2px solid #d4d4d4;border-top-color:#0a0a0a;border-radius:50%;animation:spin .8s linear infinite}@keyframes spin{to{transform:rotate(360deg)}}.footnote{margin:22px 0 0;color:#a3a3a3;font-size:12px;line-height:1.55}.passkey-offer{margin-top:24px;padding-top:20px;border-top:1px solid #e5e5e5}@media(max-width:520px){body{padding:84px 20px 104px;place-items:start center}h1{font-size:25px}}`;}
