import assert from "node:assert/strict";
import test from "node:test";
import { exportJWK, generateKeyPair } from "jose";
import type { Config } from "../src/config.js";
import { pkceChallenge, TokenService } from "../src/security.js";
import { assertSafeResourceUrl, limitResponseBody } from "../src/network.js";

async function config():Promise<Config>{const {privateKey}=await generateKeyPair("ES256",{extractable:true});const privateJwk=await exportJWK(privateKey);return{PUBLIC_BASE_URL:"https://pay.example.com",MCP_DANGEROUSLY_ALLOW_INSECURE_ISSUER_URL:false,PORT:3000,DATABASE_URL:"postgres://localhost/test",OAUTH_SIGNING_PRIVATE_JWK:JSON.stringify(privateJwk),GOOGLE_CLIENT_ID:"g",GOOGLE_CLIENT_SECRET:"g",GITHUB_CLIENT_ID:"h",GITHUB_CLIENT_SECRET:"h",CDP_API_KEY_ID:"c",CDP_API_KEY_SECRET:"c",CDP_WALLET_SECRET:"c",ACCESS_TOKEN_TTL_SECONDS:900,REFRESH_TOKEN_TTL_SECONDS:3600,AUTH_CODE_TTL_SECONDS:300,PREVIEW_TTL_SECONDS:120,MAX_PAYMENT_USDC_ATOMIC:"1000000",MAX_DAILY_USDC_ATOMIC:"5000000",PAYMENT_TIMEOUT_MS:15000,privateJwk,issuer:"https://pay.example.com",resource:"https://pay.example.com/mcp"};}

test("PKCE uses base64url SHA-256",()=>assert.equal(pkceChallenge("verifier"),"iMnq5o6zALKXGivsnlom_0F5_WYda32GHkxlV7mq7hQ"));

test("access tokens bind user, client and MCP resource",async()=>{const c=await config();const service=await TokenService.create(c);const token=await service.accessToken("user-1","client-1",["x402:pay"]);const verified=await service.verifyAccessToken(token);assert.equal(verified.userId,"user-1");assert.equal(verified.clientId,"client-1");assert.deepEqual(verified.scopes,["x402:pay"]);});

test("OAuth provider state is signed and bound to the callback provider",async()=>{const service=await TokenService.create(await config());const state=await service.providerState("login-state","github");assert.equal(await service.verifyProviderState(state,"github"),"login-state");await assert.rejects(()=>service.verifyProviderState(state,"google"),/invalid OAuth provider state/);});

test("Bazaar references are signed and tamper evident",async()=>{const service=await TokenService.create(await config());const ref=await service.serviceRef("https://api.example.com/report");assert.equal(await service.verifyServiceRef(ref),"https://api.example.com/report");const parts=ref.split(".");parts[1]=`${parts[1]![0]==="A"?"B":"A"}${parts[1]!.slice(1)}`;await assert.rejects(()=>service.verifyServiceRef(parts.join(".")));});

test("resource URL guard rejects SSRF-shaped destinations",()=>{assert.equal(assertSafeResourceUrl("https://api.example.com/path").hostname,"api.example.com");assert.throws(()=>assertSafeResourceUrl("http://api.example.com"));assert.throws(()=>assertSafeResourceUrl("https://127.0.0.1/"));assert.throws(()=>assertSafeResourceUrl("https://169.254.169.254/latest/meta-data"));assert.throws(()=>assertSafeResourceUrl("https://user:pass@example.com"));});

test("resource URL guard rejects non-public IPv4 and IPv6 literals",()=>{
  for(const url of ["https://[::1]/","https://[::ffff:127.0.0.1]/","https://[fd00::1]/","https://[fe80::1]/","https://100.64.0.1/","https://198.18.0.1/"])assert.throws(()=>assertSafeResourceUrl(url),url);
  assert.equal(assertSafeResourceUrl("https://1.1.1.1/resource").hostname,"1.1.1.1");
  assert.equal(assertSafeResourceUrl("https://[2606:4700:4700::1111]/resource").hostname,"[2606:4700:4700::1111]");
});

test("response body limit applies before the x402 SDK can buffer a 402 body",async()=>{
  const oversized=new Response(new ReadableStream<Uint8Array>({start(controller){controller.enqueue(new Uint8Array(600_000));controller.enqueue(new Uint8Array(600_000));controller.close();}}),{status:402});
  await assert.rejects(()=>limitResponseBody(oversized,1_000_000).text(),/too large/);
  const declared=new Response("small",{status:402,headers:{"content-length":"1000001"}});
  assert.throws(()=>limitResponseBody(declared,1_000_000),/too large/);
});
