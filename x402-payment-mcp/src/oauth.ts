import express, { type Request, type Response } from "express";
import type { Config } from "./config.js";
import { pkceChallenge, randomToken, safeEqual, TokenService } from "./security.js";
import { Store } from "./store.js";

const ALLOWED_SCOPE = "x402:pay";

export function oauthRouter(config: Config, store: Store, tokens: TokenService) {
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
    scopes_supported: [ALLOWED_SCOPE],
  }));
  router.get("/.well-known/oauth-protected-resource", (_req, res) => protectedMetadata(config, res));
  router.get("/.well-known/oauth-protected-resource/mcp", (_req, res) => protectedMetadata(config, res));
  router.get("/oauth/jwks", (_req, res) => res.set("Access-Control-Allow-Origin","*").json({ keys: [tokens.publicJwk] }));

  router.post("/oauth/register", asyncRoute(async (req, res) => {
    const body = req.body as Record<string, unknown>;
    if (!Array.isArray(body.redirect_uris) || body.redirect_uris.length === 0 || !body.redirect_uris.every((u) => typeof u === "string" && validRedirectUri(u))) {
      return oauthJsonError(res, 400, "invalid_redirect_uri", "redirect_uris must contain HTTPS or loopback URLs");
    }
    if (body.token_endpoint_auth_method && body.token_endpoint_auth_method !== "none") return oauthJsonError(res, 400, "invalid_client_metadata", "only public clients are supported");
    const client = await store.registerClient(typeof body.client_name === "string" ? body.client_name.slice(0, 200) : "MCP client", body.redirect_uris as string[]);
    res.status(201).json({ client_id: client.clientId, client_name: client.clientName, redirect_uris: client.redirectUris, token_endpoint_auth_method: "none", grant_types: ["authorization_code", "refresh_token"], response_types: ["code"] });
  }));

  router.get("/oauth/authorize", asyncRoute(async (req, res) => {
    const p = authorizeParams(req);
    const error = await validateAuthorize(p, store, config);
    if (error) return oauthJsonError(res, 400, "invalid_request", error);
    const stateId = await store.createLoginState({ clientId:p.clientId, redirectUri:p.redirectUri, state:p.state, codeChallenge:p.codeChallenge, resource:p.resource, scope:ALLOWED_SCOPE });
    const google = `/auth/google/start?login_state=${encodeURIComponent(stateId)}`;
    const github = `/auth/github/start?login_state=${encodeURIComponent(stateId)}`;
    res.type("html").send(loginPage(google, github));
  }));

  router.get("/auth/google/start", (req, res) => {
    const loginState = requiredQuery(req, "login_state");
    const url = new URL("https://accounts.google.com/o/oauth2/v2/auth");
    url.search = new URLSearchParams({ client_id:config.GOOGLE_CLIENT_ID, redirect_uri:`${config.issuer}/auth/google/callback`, response_type:"code", scope:"openid email profile", state:loginState, prompt:"select_account" }).toString();
    res.redirect(url.toString());
  });
  router.get("/auth/github/start", (req, res) => {
    const loginState = requiredQuery(req, "login_state");
    const url = new URL("https://github.com/login/oauth/authorize");
    url.search = new URLSearchParams({ client_id:config.GITHUB_CLIENT_ID, redirect_uri:`${config.issuer}/auth/github/callback`, scope:"read:user user:email", state:loginState }).toString();
    res.redirect(url.toString());
  });

  router.get("/auth/google/callback", asyncRoute(async (req, res) => {
    const state = await consumeCallbackState(req, store);
    const code = requiredQuery(req, "code");
    const token = await postForm("https://oauth2.googleapis.com/token", { code, client_id:config.GOOGLE_CLIENT_ID, client_secret:config.GOOGLE_CLIENT_SECRET, redirect_uri:`${config.issuer}/auth/google/callback`, grant_type:"authorization_code" });
    const profile = await getJson("https://openidconnect.googleapis.com/v1/userinfo", String(token.access_token));
    if (typeof profile.sub !== "string") throw new Error("Google did not return a subject");
    const userId = await store.upsertIdentity("google", profile.sub, stringOrNull(profile.name), stringOrNull(profile.email));
    await finishLogin(res, store, config, state, userId);
  }));
  router.get("/auth/github/callback", asyncRoute(async (req, res) => {
    const state = await consumeCallbackState(req, store);
    const code = requiredQuery(req, "code");
    const token = await postForm("https://github.com/login/oauth/access_token", { code, client_id:config.GITHUB_CLIENT_ID, client_secret:config.GITHUB_CLIENT_SECRET, redirect_uri:`${config.issuer}/auth/github/callback` });
    const profile = await getJson("https://api.github.com/user", String(token.access_token), { "User-Agent":"AgentLayer-x402-MCP", Accept:"application/vnd.github+json" });
    if (typeof profile.id !== "number" && typeof profile.id !== "string") throw new Error("GitHub did not return a subject");
    const userId = await store.upsertIdentity("github", String(profile.id), stringOrNull(profile.name ?? profile.login), stringOrNull(profile.email));
    await finishLogin(res, store, config, state, userId);
  }));

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

function protectedMetadata(config:Config,res:Response){res.set("Access-Control-Allow-Origin","*").json({resource:config.resource,authorization_servers:[config.issuer],scopes_supported:[ALLOWED_SCOPE],bearer_methods_supported:["header"]});}
function authorizeParams(req:Request){return{clientId:requiredQuery(req,"client_id"),redirectUri:requiredQuery(req,"redirect_uri"),state:requiredQuery(req,"state"),codeChallenge:requiredQuery(req,"code_challenge"),resource:requiredQuery(req,"resource"),responseType:requiredQuery(req,"response_type"),challengeMethod:requiredQuery(req,"code_challenge_method"),scope:typeof req.query.scope==="string"?req.query.scope:ALLOWED_SCOPE};}
async function validateAuthorize(p:ReturnType<typeof authorizeParams>,store:Store,config:Config){const c=await store.getClient(p.clientId);if(!c)return"unknown client_id";if(!c.redirectUris.includes(p.redirectUri))return"redirect_uri is not registered";if(p.responseType!=="code")return"only response_type=code is supported";if(p.challengeMethod!=="S256"||p.codeChallenge.length<43)return"PKCE S256 is required";if(p.resource!==config.resource)return"resource must identify this MCP server";if(p.scope.split(" ").some(s=>s!==ALLOWED_SCOPE))return"unsupported scope";return null;}
async function consumeCallbackState(req:Request,store:Store){const state=requiredQuery(req,"state");const row=await store.consumeLoginState(state);if(!row)throw new Error("invalid or expired login state");return row;}
async function finishLogin(res:Response,store:Store,config:Config,state:Awaited<ReturnType<typeof consumeCallbackState>>,userId:string){const code=await store.createAuthorizationCode(state,userId,config.AUTH_CODE_TTL_SECONDS);const redirect=new URL(state.redirectUri);redirect.searchParams.set("code",code);redirect.searchParams.set("state",state.state);res.redirect(redirect.toString());}
async function postForm(url:string,body:Record<string,string>){const r=await fetch(url,{method:"POST",headers:{Accept:"application/json","Content-Type":"application/x-www-form-urlencoded"},body:new URLSearchParams(body),signal:AbortSignal.timeout(10000)});if(!r.ok)throw new Error(`OAuth provider token exchange failed (${r.status})`);return r.json() as Promise<Record<string,unknown>>;}
async function getJson(url:string,token:string,headers:Record<string,string>={}){const r=await fetch(url,{headers:{...headers,Authorization:`Bearer ${token}`},signal:AbortSignal.timeout(10000)});if(!r.ok)throw new Error(`OAuth provider profile request failed (${r.status})`);return r.json() as Promise<Record<string,unknown>>;}
function requiredQuery(req:Request,name:string){const v=req.query[name];if(typeof v!=="string"||!v)throw new Error(`missing ${name}`);return v;}
function validRedirectUri(value:string){try{const u=new URL(value);return u.protocol==="https:"||(u.protocol==="http:"&&["localhost","127.0.0.1","::1"].includes(u.hostname));}catch{return false;}}
function stringOrNull(v:unknown){return typeof v==="string"?v:null;}
function oauthJsonError(res:Response,status:number,error:string,description:string){return res.status(status).json({error,error_description:description});}
function asyncRoute(fn:(req:Request,res:Response)=>Promise<unknown>){return(req:Request,res:Response,next:express.NextFunction)=>{Promise.resolve(fn(req,res)).catch(next);};}
function loginPage(google:string,github:string){return `<!doctype html><html><head><meta name="viewport" content="width=device-width"><title>Connect x402 wallet</title><style>body{font:16px system-ui;max-width:440px;margin:12vh auto;padding:24px;color:#171717}a{display:block;margin:12px 0;padding:14px;text-align:center;border:1px solid #bbb;border-radius:10px;text-decoration:none;color:inherit}small{color:#666}</style></head><body><h1>Connect x402 wallet</h1><p>Sign in once. Your Base wallet and limits follow your account across chats and devices.</p><a href="${google}">Continue with Google</a><a href="${github}">Continue with GitHub</a><small>This grants the MCP permission to make only previewed Base USDC x402 payments within configured limits.</small></body></html>`;}
