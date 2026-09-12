import assert from "node:assert/strict";
import test from "node:test";
import express from "express";
import type { AddressInfo } from "node:net";
import type { Config } from "../src/config.js";
import { oauthRouter } from "../src/oauth.js";
import { pkceChallenge } from "../src/security.js";
import type { LoginState, OAuthClient, Store } from "../src/store.js";
import type { TokenService } from "../src/security.js";

test("OAuth consent and provider callback are bound to the initiating browser",async()=>{
  const client:OAuthClient={clientId:"attacker-client",clientName:'Untrusted <script>alert(1)</script>',redirectUris:["https://attacker.example/callback"]};
  let saved:(LoginState&{browserSessionHash:string;csrfTokenHash:string;approved:boolean;provider?:"google"|"github"})|null=null;
  const store={
    getClient:async(id:string)=>id===client.clientId?client:null,
    consumeRateLimit:async()=>true,
    createLoginState:async(data:Omit<LoginState,"id">,browserSessionHash:string,csrfTokenHash:string)=>{saved={...data,id:"login-state",browserSessionHash,csrfTokenHash,approved:false};return saved.id;},
    approveLoginState:async(id:string,browserSessionHash:string,csrfTokenHash:string,provider:"google"|"github")=>{if(!saved||saved.id!==id||saved.browserSessionHash!==browserSessionHash||saved.csrfTokenHash!==csrfTokenHash||(saved.provider&&saved.provider!==provider))return false;saved.approved=true;saved.provider=provider;return true;},
    consumeLoginState:async(id:string,browserSessionHash:string,provider:"google"|"github")=>{if(!saved||saved.id!==id||saved.browserSessionHash!==browserSessionHash||!saved.approved||saved.provider!==provider)return null;const result=saved;saved=null;return result;},
    upsertIdentity:async()=>"victim-user",
    createAuthorizationCode:async()=>"authorization-code",
  } as unknown as Store;
  const config={issuer:"https://pay.example",resource:"https://pay.example/mcp",GITHUB_CLIENT_ID:"github-id",GITHUB_CLIENT_SECRET:"github-secret",ACCESS_TOKEN_TTL_SECONDS:900,AUTH_CODE_TTL_SECONDS:300} as Config;
  const tokens={publicJwk:{}} as unknown as TokenService;
  const app=express();app.use(oauthRouter(config,store,tokens));app.use((_error:unknown,_req:express.Request,res:express.Response,_next:express.NextFunction)=>res.status(400).json({error:"invalid_request"}));
  const server=app.listen(0,"127.0.0.1");await new Promise<void>(resolve=>server.once("listening",resolve));const base=`http://127.0.0.1:${(server.address() as AddressInfo).port}`;
  const realFetch=globalThis.fetch;
  try{
    const query=new URLSearchParams({client_id:client.clientId,redirect_uri:client.redirectUris[0]!,state:"client-state",code_challenge:pkceChallenge("client-verifier"),resource:config.resource,response_type:"code",code_challenge_method:"S256"});
    const authorize=await realFetch(`${base}/oauth/authorize?${query}`);const page=await authorize.text();const setCookie=authorize.headers.get("set-cookie");
    assert.equal(authorize.status,200);assert.match(setCookie??"",/^__Host-x402_oauth_session=/);assert.ok(setCookie?.includes("HttpOnly; Secure; SameSite=Lax"));assert.match(page,/Untrusted &lt;script&gt;alert\(1\)&lt;\/script&gt;/);assert.match(page,/attacker\.example/);assert.doesNotMatch(page,/<script>alert/);
    const state=hidden(page,"login_state");const csrf=hidden(page,"csrf_token");const cookie=setCookie!.split(";",1)[0]!;

    const consentBody=new URLSearchParams({login_state:state,csrf_token:csrf,provider:"github"});
    const noCookie=await realFetch(`${base}/oauth/consent`,{method:"POST",body:consentBody,redirect:"manual"});assert.equal(noCookie.status,400);
    const badCsrf=await realFetch(`${base}/oauth/consent`,{method:"POST",headers:{Cookie:cookie},body:new URLSearchParams({login_state:state,csrf_token:"wrong",provider:"github"}),redirect:"manual"});assert.equal(badCsrf.status,400);
    const consent=await realFetch(`${base}/oauth/consent`,{method:"POST",headers:{Cookie:cookie},body:consentBody,redirect:"manual"});assert.equal(consent.status,302);assert.equal(new URL(consent.headers.get("location")!).searchParams.get("state"),state);
    const repeatedConsent=await realFetch(`${base}/oauth/consent`,{method:"POST",headers:{Cookie:cookie},body:consentBody,redirect:"manual"});assert.equal(repeatedConsent.status,302);

    const callbackWithoutCookie=await realFetch(`${base}/auth/github/callback?state=${state}&code=provider-code`,{redirect:"manual"});assert.equal(callbackWithoutCookie.status,400);assert.ok(saved,"a callback from another browser must not consume the login state");
    globalThis.fetch=async(input,init)=>String(input)==="https://github.com/login/oauth/access_token"?Response.json({access_token:"provider-token"}):String(input)==="https://api.github.com/user"?Response.json({id:123,name:"Victim"}):realFetch(input,init);
    const callback=await realFetch(`${base}/auth/github/callback?state=${state}&code=provider-code`,{headers:{Cookie:cookie},redirect:"manual"});assert.equal(callback.status,302);assert.equal(callback.headers.get("location"),"https://attacker.example/callback?code=authorization-code&state=client-state");
    const replay=await realFetch(`${base}/auth/github/callback?state=${state}&code=provider-code`,{headers:{Cookie:cookie},redirect:"manual"});assert.equal(replay.status,400);
  }finally{globalThis.fetch=realFetch;await new Promise<void>((resolve,reject)=>server.close(error=>error?reject(error):resolve()));}
});

test("OAuth authorization stops before creating state when the durable quota is exhausted",async()=>{
  let created=false;const store={consumeRateLimit:async(bucket:string)=>bucket!=="oauth_authorize_ip",getClient:async()=>{throw new Error("must not query client after rate limit");},createLoginState:async()=>{created=true;throw new Error("must not create state");}} as unknown as Store;
  const config={issuer:"https://pay.example",resource:"https://pay.example/mcp",GITHUB_CLIENT_ID:"github-id",GITHUB_CLIENT_SECRET:"github-secret"} as Config;const tokens={publicJwk:{}} as unknown as TokenService;
  const app=express();app.set("trust proxy",1);app.use(oauthRouter(config,store,tokens));const server=app.listen(0,"127.0.0.1");await new Promise<void>(resolve=>server.once("listening",resolve));const base=`http://127.0.0.1:${(server.address() as AddressInfo).port}`;
  try{const response=await fetch(`${base}/oauth/authorize`);assert.equal(response.status,429);assert.equal(response.headers.get("retry-after"),"600");assert.equal(created,false);}finally{await new Promise<void>((resolve,reject)=>server.close(error=>error?reject(error):resolve()));}
});

function hidden(page:string,name:string){const match=page.match(new RegExp(`name="${name}" value="([^"]+)"`));assert.ok(match);return match[1]!;}
