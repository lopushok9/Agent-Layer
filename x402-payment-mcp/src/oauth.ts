import express, { type Request, type Response } from "express";
import type { Config } from "./config.js";
import { pkceChallenge, randomToken, safeEqual, TokenService } from "./security.js";
import { Store } from "./store.js";

const ALLOWED_SCOPE = "x402:pay";
const BROWSER_SESSION_COOKIE = "__Host-x402_oauth_session";

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
    const p = authorizeParams(req);
    const error = await validateAuthorize(p, store, config);
    if (error) return oauthJsonError(res, 400, "invalid_request", error);
    const client=await store.getClient(p.clientId);if(!client)return oauthJsonError(res,400,"invalid_request","unknown client_id");
    const browserSession=readBrowserCookie(req)??randomToken();const csrfToken=randomToken();
    const stateId = await store.createLoginState({ clientId:p.clientId, redirectUri:p.redirectUri, state:p.state, codeChallenge:p.codeChallenge, resource:p.resource, scope:ALLOWED_SCOPE },pkceChallenge(browserSession),pkceChallenge(csrfToken));
    setBrowserCookie(res,browserSession);
    res.set("Cache-Control","no-store").set("Content-Security-Policy","default-src 'none'; style-src 'unsafe-inline'; form-action 'self'; frame-ancestors 'none'; base-uri 'none'").set("X-Frame-Options","DENY").set("Referrer-Policy","no-referrer");
    res.type("html").send(consentPage({stateId,csrfToken,clientName:client.clientName,redirectOrigin:new URL(p.redirectUri).origin,google:Boolean(config.GOOGLE_CLIENT_ID),github:Boolean(config.GITHUB_CLIENT_ID)}));
  }));

  router.post("/oauth/consent",express.urlencoded({extended:false,limit:"8kb"}),asyncRoute(async(req,res)=>{
    const stateId=requiredBody(req,"login_state");const csrfToken=requiredBody(req,"csrf_token");const provider=requiredBody(req,"provider");
    if(provider!=="google"&&provider!=="github")return oauthJsonError(res,400,"invalid_request","unsupported identity provider");
    if((provider==="google"&&!config.GOOGLE_CLIENT_ID)||(provider==="github"&&!config.GITHUB_CLIENT_ID))return oauthJsonError(res,400,"invalid_request","identity provider is not configured");
    const browserSession=readBrowserCookie(req);if(!browserSession)return oauthJsonError(res,400,"invalid_request","authorization session is missing or expired");
    const approved=await store.approveLoginState(stateId,pkceChallenge(browserSession),pkceChallenge(csrfToken),provider);if(!approved)return oauthJsonError(res,400,"invalid_request","authorization request is invalid or expired");
    res.redirect(providerAuthorizationUrl(provider,stateId,config));
  }));

  const googleConfig=config.GOOGLE_CLIENT_ID&&config.GOOGLE_CLIENT_SECRET?{id:config.GOOGLE_CLIENT_ID,secret:config.GOOGLE_CLIENT_SECRET}:null;
  if(googleConfig){
    router.get("/auth/google/callback", asyncRoute(async (req, res) => {
      const state = await consumeCallbackState(req, store,"google");const code = requiredQuery(req, "code");
      const token = await postForm("https://oauth2.googleapis.com/token", { code, client_id:googleConfig.id, client_secret:googleConfig.secret, redirect_uri:`${config.issuer}/auth/google/callback`, grant_type:"authorization_code" });
      const profile = await getJson("https://openidconnect.googleapis.com/v1/userinfo", String(token.access_token));
      if (typeof profile.sub !== "string") throw new Error("Google did not return a subject");
      const userId = await store.upsertIdentity("google", profile.sub, stringOrNull(profile.name), stringOrNull(profile.email));await finishLogin(res, store, config, state, userId);
    }));
  }
  const githubConfig=config.GITHUB_CLIENT_ID&&config.GITHUB_CLIENT_SECRET?{id:config.GITHUB_CLIENT_ID,secret:config.GITHUB_CLIENT_SECRET}:null;
  if(githubConfig){
    router.get("/auth/github/callback", asyncRoute(async (req, res) => {
      const state = await consumeCallbackState(req, store,"github");const code = requiredQuery(req, "code");
      const token = await postForm("https://github.com/login/oauth/access_token", { code, client_id:githubConfig.id, client_secret:githubConfig.secret, redirect_uri:`${config.issuer}/auth/github/callback` });
      const profile = await getJson("https://api.github.com/user", String(token.access_token), { "User-Agent":"AgentLayer-x402-MCP", Accept:"application/vnd.github+json" });
      if (typeof profile.id !== "number" && typeof profile.id !== "string") throw new Error("GitHub did not return a subject");
      const userId = await store.upsertIdentity("github", String(profile.id), stringOrNull(profile.name ?? profile.login), stringOrNull(profile.email));await finishLogin(res, store, config, state, userId);
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

function protectedMetadata(config:Config,res:Response){res.set("Access-Control-Allow-Origin","*").json({resource:config.resource,authorization_servers:[config.issuer],scopes_supported:[ALLOWED_SCOPE],bearer_methods_supported:["header"]});}
function authorizeParams(req:Request){return{clientId:requiredQuery(req,"client_id"),redirectUri:requiredQuery(req,"redirect_uri"),state:requiredQuery(req,"state"),codeChallenge:requiredQuery(req,"code_challenge"),resource:requiredQuery(req,"resource"),responseType:requiredQuery(req,"response_type"),challengeMethod:requiredQuery(req,"code_challenge_method"),scope:typeof req.query.scope==="string"?req.query.scope:ALLOWED_SCOPE};}
async function validateAuthorize(p:ReturnType<typeof authorizeParams>,store:Store,config:Config){const c=await store.getClient(p.clientId);if(!c)return"unknown client_id";if(!c.redirectUris.includes(p.redirectUri))return"redirect_uri is not registered";if(p.responseType!=="code")return"only response_type=code is supported";if(p.challengeMethod!=="S256"||p.codeChallenge.length<43)return"PKCE S256 is required";if(p.resource!==config.resource)return"resource must identify this MCP server";if(p.scope.split(" ").some(s=>s!==ALLOWED_SCOPE))return"unsupported scope";return null;}
async function consumeCallbackState(req:Request,store:Store,provider:"google"|"github"){const state=requiredQuery(req,"state");const browserSession=readBrowserCookie(req);if(!browserSession)throw new Error("authorization session is missing or expired");const row=await store.consumeLoginState(state,pkceChallenge(browserSession),provider);if(!row)throw new Error("invalid or expired login state");return row;}
async function finishLogin(res:Response,store:Store,config:Config,state:Awaited<ReturnType<typeof consumeCallbackState>>,userId:string){const code=await store.createAuthorizationCode(state,userId,config.AUTH_CODE_TTL_SECONDS);const redirect=new URL(state.redirectUri);redirect.searchParams.set("code",code);redirect.searchParams.set("state",state.state);res.redirect(redirect.toString());}
async function postForm(url:string,body:Record<string,string>){const r=await fetch(url,{method:"POST",headers:{Accept:"application/json","Content-Type":"application/x-www-form-urlencoded"},body:new URLSearchParams(body),signal:AbortSignal.timeout(10000)});if(!r.ok)throw new Error(`OAuth provider token exchange failed (${r.status})`);return r.json() as Promise<Record<string,unknown>>;}
async function getJson(url:string,token:string,headers:Record<string,string>={}){const r=await fetch(url,{headers:{...headers,Authorization:`Bearer ${token}`},signal:AbortSignal.timeout(10000)});if(!r.ok)throw new Error(`OAuth provider profile request failed (${r.status})`);return r.json() as Promise<Record<string,unknown>>;}
function requiredQuery(req:Request,name:string){const v=req.query[name];if(typeof v!=="string"||!v)throw new Error(`missing ${name}`);return v;}
function requiredBody(req:Request,name:string){const v=req.body?.[name];if(typeof v!=="string"||!v)throw new Error(`missing ${name}`);return v;}
function validRedirectUri(value:string){try{const u=new URL(value);return u.protocol==="https:"||(u.protocol==="http:"&&["localhost","127.0.0.1","::1"].includes(u.hostname));}catch{return false;}}
function stringOrNull(v:unknown){return typeof v==="string"?v:null;}
function oauthJsonError(res:Response,status:number,error:string,description:string){return res.status(status).json({error,error_description:description});}
async function withinOAuthLimits(req:Request,store:Store,bucket:string,perIp:number,windowSeconds:number,global:number){const ip=pkceChallenge(req.ip||req.socket.remoteAddress||"unknown");const [ipAllowed,globalAllowed]=await Promise.all([store.consumeRateLimit(`oauth_${bucket}_ip`,ip,perIp,windowSeconds),store.consumeRateLimit(`oauth_${bucket}_global`,"global",global,windowSeconds)]);return ipAllowed&&globalAllowed;}
function rateLimitError(res:Response,retryAfter:number){return res.status(429).set("Retry-After",String(retryAfter)).json({error:"temporarily_unavailable",error_description:"too many OAuth requests"});}
function asyncRoute(fn:(req:Request,res:Response)=>Promise<unknown>){return(req:Request,res:Response,next:express.NextFunction)=>{Promise.resolve(fn(req,res)).catch(next);};}
function providerAuthorizationUrl(provider:"google"|"github",state:string,config:Config){if(provider==="google"){const url=new URL("https://accounts.google.com/o/oauth2/v2/auth");url.search=new URLSearchParams({client_id:config.GOOGLE_CLIENT_ID!,redirect_uri:`${config.issuer}/auth/google/callback`,response_type:"code",scope:"openid email profile",state,prompt:"select_account"}).toString();return url.toString();}const url=new URL("https://github.com/login/oauth/authorize");url.search=new URLSearchParams({client_id:config.GITHUB_CLIENT_ID!,redirect_uri:`${config.issuer}/auth/github/callback`,scope:"read:user user:email",state}).toString();return url.toString();}
function setBrowserCookie(res:Response,value:string){res.append("Set-Cookie",`${BROWSER_SESSION_COOKIE}=${value}; Max-Age=3600; Path=/; HttpOnly; Secure; SameSite=Lax`);}
function readBrowserCookie(req:Request){for(const part of (req.headers.cookie??"").split(";")){const i=part.indexOf("=");if(i<0)continue;if(part.slice(0,i).trim()===BROWSER_SESSION_COOKIE)return part.slice(i+1).trim();}return null;}
function html(value:string){return value.replaceAll("&","&amp;").replaceAll("<","&lt;").replaceAll(">","&gt;").replaceAll('"',"&quot;").replaceAll("'","&#39;");}
function consentPage(input:{stateId:string;csrfToken:string;clientName:string;redirectOrigin:string;google:boolean;github:boolean}){const buttons=[input.google?'<button name="provider" value="google">Continue with Google</button>':"",input.github?'<button name="provider" value="github">Continue with GitHub</button>':""].join("");return `<!doctype html><html><head><meta name="viewport" content="width=device-width"><title>Authorize x402 wallet</title><style>body{font:16px system-ui;max-width:480px;margin:10vh auto;padding:24px;color:#171717}code{overflow-wrap:anywhere}button{display:block;width:100%;margin:12px 0;padding:14px;background:white;border:1px solid #bbb;border-radius:10px;font:inherit;cursor:pointer}small{color:#666}</style></head><body><h1>Authorize x402 wallet</h1><p><strong>${html(input.clientName)}</strong> is requesting access to your x402 wallet.</p><p>After sign-in, access will return to <code>${html(input.redirectOrigin)}</code>.</p><p>Permission: preview and make Base USDC x402 payments within the server limits.</p><form method="post" action="/oauth/consent"><input type="hidden" name="login_state" value="${html(input.stateId)}"><input type="hidden" name="csrf_token" value="${html(input.csrfToken)}">${buttons}</form><small>Continue only if you recognize this client and return address.</small></body></html>`;}
