import assert from "node:assert/strict";
import test from "node:test";
import express from "express";
import type { AddressInfo } from "node:net";
import type { Config } from "../src/config.js";
import { oauthRouter } from "../src/oauth.js";
import { pkceChallenge } from "../src/security.js";
import type { AuthorizationCode, LoginState, OAuthClient, Store } from "../src/store.js";
import type { TokenService } from "../src/security.js";

test("OAuth authenticates first and grants a requesting client only after explicit one-time consent",async()=>{
  const client:OAuthClient={clientId:"attacker-client",clientName:'Untrusted <script>alert(1)</script>',redirectUris:["https://attacker.example/callback"]};
  let saved:LoginState|null=null;let pending:AuthorizationCode|null=null;let approved=false;
  const store={
    getClient:async(id:string)=>id===client.clientId?client:null,
    consumeRateLimit:async()=>true,
    createLoginState:async(data:Omit<LoginState,"id">)=>{saved={...data,id:"login-state"};return saved.id;},
    hasLoginState:async(id:string)=>saved?.id===id,
    consumeLoginState:async(id:string)=>{if(saved?.id!==id)return null;const result=saved;saved=null;return result;},
    upsertIdentity:async()=>"victim-user",
    createPendingConsent:async(state:LoginState,userId:string)=>{pending={...state,userId};return "pending-consent";},
    approvePendingConsent:async(token:string)=>{if(token!=="pending-consent"||!pending)return null;approved=true;return pending;},
    denyPendingConsent:async(token:string)=>{if(token!=="pending-consent"||!pending||approved)return null;const result=pending;pending=null;return result;},
  } as unknown as Store;
  const config={issuer:"https://pay.example",resource:"https://pay.example/mcp",GITHUB_CLIENT_ID:"github-id",GITHUB_CLIENT_SECRET:"github-secret",ACCESS_TOKEN_TTL_SECONDS:900,AUTH_CODE_TTL_SECONDS:300} as Config;
  const tokens={
    publicJwk:{},
    providerState:async(id:string,provider:string)=>`signed-${provider}-${id}`,
    verifyProviderState:async(value:string,provider:string)=>{if(value!==`signed-${provider}-login-state`)throw new Error("bad provider state");return "login-state";},
  } as unknown as TokenService;
  const app=express();app.use(oauthRouter(config,store,tokens));app.use((_error:unknown,_req:express.Request,res:express.Response,_next:express.NextFunction)=>res.status(400).json({error:"invalid_request"}));
  const server=app.listen(0,"127.0.0.1");await new Promise<void>(resolve=>server.once("listening",resolve));const base=`http://127.0.0.1:${(server.address() as AddressInfo).port}`;
  const realFetch=globalThis.fetch;
  try{
    const query=new URLSearchParams({client_id:client.clientId,redirect_uri:client.redirectUris[0]!,state:"client-state",code_challenge:pkceChallenge("client-verifier"),resource:config.resource,response_type:"code",code_challenge_method:"S256"});
    const authorize=await realFetch(`${base}/oauth/authorize?${query}`);const page=await authorize.text();
    assert.equal(authorize.status,200);assert.equal(authorize.headers.get("set-cookie"),null);assert.match(authorize.headers.get("content-security-policy")??"",/script-src 'nonce-/);assert.match(page,/Continue with GitHub/);assert.match(page,/Opening "/);assert.match(page,/color:#171717!important/);assert.match(page,/Untrusted &lt;script&gt;alert\(1\)&lt;\/script&gt;/);assert.doesNotMatch(page,/<script>alert/);
    const state=linkParam(page,"/auth/github/start","login_state");
    const start=await realFetch(`${base}/auth/github/start?login_state=${encodeURIComponent(state)}`,{redirect:"manual"});
    assert.equal(start.status,302);assert.equal(new URL(start.headers.get("location")!).searchParams.get("state"),"signed-github-login-state");

    globalThis.fetch=async(input,init)=>String(input)==="https://github.com/login/oauth/access_token"?Response.json({access_token:"provider-token"}):String(input)==="https://api.github.com/user"?Response.json({id:123,name:"Victim"}):realFetch(input,init);
    const callback=await realFetch(`${base}/auth/github/callback?state=signed-github-login-state&code=provider-code`,{redirect:"manual"});const consentPage=await callback.text();
    assert.equal(callback.status,200);assert.equal(callback.headers.get("location"),null);assert.match(consentPage,/attacker\.example/);assert.match(consentPage,/Allow access/);assert.match(consentPage,/Connecting to the MCP client/);assert.match(consentPage,/Cancel/);
    assert.ok(pending,"provider login alone must not issue an authorization code or redirect to the client");

    const invalidConsent=await realFetch(`${base}/oauth/consent`,{method:"POST",body:new URLSearchParams({consent_token:"wrong",decision:"allow"}),redirect:"manual"});assert.equal(invalidConsent.status,400);
    const consentToken=hidden(consentPage,"consent_token");
    const consent=await realFetch(`${base}/oauth/consent`,{method:"POST",body:new URLSearchParams({consent_token:consentToken,decision:"allow"}),redirect:"manual"});
    assert.equal(consent.status,303);assert.equal(consent.headers.get("location"),"https://attacker.example/callback?code=pending-consent&state=client-state");
    const replay=await realFetch(`${base}/oauth/consent`,{method:"POST",body:new URLSearchParams({consent_token:consentToken,decision:"allow"}),redirect:"manual"});assert.equal(replay.status,303);assert.equal(replay.headers.get("location"),consent.headers.get("location"));
    const callbackReplay=await realFetch(`${base}/auth/github/callback?state=signed-github-login-state&code=provider-code`,{redirect:"manual"});assert.equal(callbackReplay.status,400);
  }finally{globalThis.fetch=realFetch;await new Promise<void>((resolve,reject)=>server.close(error=>error?reject(error):resolve()));}
});

test("OAuth denial returns access_denied and cannot be replayed",async()=>{
  const grant:AuthorizationCode={id:"",userId:"user",clientId:"client",redirectUri:"https://client.example/callback",state:"client-state",codeChallenge:"challenge",resource:"https://pay.example/mcp",scope:"x402:pay"};
  let available=true;
  const store={approvePendingConsent:async()=>null,denyPendingConsent:async(token:string)=>token==="deny-token"&&available?(available=false,grant):null} as unknown as Store;
  const config={issuer:"https://pay.example",resource:"https://pay.example/mcp"} as Config;const tokens={publicJwk:{}} as unknown as TokenService;
  const app=express();app.use(oauthRouter(config,store,tokens));app.use((_error:unknown,_req:express.Request,res:express.Response,_next:express.NextFunction)=>res.status(400).json({error:"invalid_request"}));
  const server=app.listen(0,"127.0.0.1");await new Promise<void>(resolve=>server.once("listening",resolve));const base=`http://127.0.0.1:${(server.address() as AddressInfo).port}`;
  try{const response=await fetch(`${base}/oauth/consent`,{method:"POST",body:new URLSearchParams({consent_token:"deny-token",decision:"deny"}),redirect:"manual"});assert.equal(response.status,303);const redirect=new URL(response.headers.get("location")!);assert.equal(redirect.searchParams.get("error"),"access_denied");assert.equal(redirect.searchParams.get("state"),"client-state");const replay=await fetch(`${base}/oauth/consent`,{method:"POST",body:new URLSearchParams({consent_token:"deny-token",decision:"deny"}),redirect:"manual"});assert.equal(replay.status,400);}finally{await new Promise<void>((resolve,reject)=>server.close(error=>error?reject(error):resolve()));}
});

test("OAuth authorization stops before creating state when the durable quota is exhausted",async()=>{
  let created=false;const store={consumeRateLimit:async(bucket:string)=>bucket!=="oauth_authorize_ip",getClient:async()=>{throw new Error("must not query client after rate limit");},createLoginState:async()=>{created=true;throw new Error("must not create state");}} as unknown as Store;
  const config={issuer:"https://pay.example",resource:"https://pay.example/mcp",GITHUB_CLIENT_ID:"github-id",GITHUB_CLIENT_SECRET:"github-secret"} as Config;const tokens={publicJwk:{}} as unknown as TokenService;
  const app=express();app.set("trust proxy",1);app.use(oauthRouter(config,store,tokens));const server=app.listen(0,"127.0.0.1");await new Promise<void>(resolve=>server.once("listening",resolve));const base=`http://127.0.0.1:${(server.address() as AddressInfo).port}`;
  try{const response=await fetch(`${base}/oauth/authorize`);assert.equal(response.status,429);assert.equal(response.headers.get("retry-after"),"600");assert.equal(created,false);}finally{await new Promise<void>((resolve,reject)=>server.close(error=>error?reject(error):resolve()));}
});

function hidden(page:string,name:string){const match=page.match(new RegExp(`name="${name}" value="([^"]+)"`));assert.ok(match);return match[1]!;}
function linkParam(page:string,path:string,name:string){const match=page.match(new RegExp(`href="([^"]*${path.replaceAll("/","\\/")}[^\"]*)"`));assert.ok(match);return new URL(match[1]!,"https://pay.example").searchParams.get(name)!;}
