import assert from "node:assert/strict";
import test from "node:test";
import { exportJWK, generateKeyPair } from "jose";
import { BASE_NETWORK, BASE_USDC, type Config } from "../src/config.js";
import { pkceChallenge, TokenService } from "../src/security.js";
import { assertSafeResourceUrl, createPublicLookup, limitResponseBody } from "../src/network.js";
import { PostgresBatchChannelStorage, selectRequirement } from "../src/payments.js";
import type { Store } from "../src/store.js";
import type { PaymentRequired } from "@x402/core/types";
import type { ClientEvmSigner } from "@x402/evm";
import { UptoEvmScheme } from "@x402/evm/upto/client";
import { BatchSettlementEvmScheme } from "@x402/evm/batch-settlement/client";
import { AuthCaptureEvmScheme } from "@x402/evm/auth-capture/client";

async function config():Promise<Config>{const {privateKey}=await generateKeyPair("ES256",{extractable:true});const privateJwk=await exportJWK(privateKey);return{PUBLIC_BASE_URL:"https://pay.example.com",MCP_DANGEROUSLY_ALLOW_INSECURE_ISSUER_URL:false,PORT:3000,DATABASE_URL:"postgres://localhost/test",OAUTH_SIGNING_PRIVATE_JWK:JSON.stringify(privateJwk),GOOGLE_CLIENT_ID:"g",GOOGLE_CLIENT_SECRET:"g",GITHUB_CLIENT_ID:"h",GITHUB_CLIENT_SECRET:"h",CDP_API_KEY_ID:"c",CDP_API_KEY_SECRET:"c",CDP_WALLET_SECRET:"c",ACCESS_TOKEN_TTL_SECONDS:900,REFRESH_TOKEN_TTL_SECONDS:3600,AUTH_CODE_TTL_SECONDS:300,PREVIEW_TTL_SECONDS:120,SPEND_LIMITS_ENABLED:false,MAX_PAYMENT_USDC_ATOMIC:"1000000",MAX_DAILY_USDC_ATOMIC:"5000000",PAYMENT_TIMEOUT_MS:15000,privateJwk,issuer:"https://pay.example.com",resource:"https://pay.example.com/mcp"};}

test("PKCE uses base64url SHA-256",()=>assert.equal(pkceChallenge("verifier"),"iMnq5o6zALKXGivsnlom_0F5_WYda32GHkxlV7mq7hQ"));

test("access tokens bind user, client and MCP resource",async()=>{const c=await config();const service=await TokenService.create(c);const token=await service.accessToken("user-1","client-1",["x402:pay"]);const verified=await service.verifyAccessToken(token);assert.equal(verified.userId,"user-1");assert.equal(verified.clientId,"client-1");assert.deepEqual(verified.scopes,["x402:pay"]);});

test("OAuth provider state is signed and bound to the callback provider",async()=>{const service=await TokenService.create(await config());const state=await service.providerState("login-state","github");assert.equal(await service.verifyProviderState(state,"github"),"login-state");await assert.rejects(()=>service.verifyProviderState(state,"google"),/invalid OAuth provider state/);});

test("Bazaar references are signed and tamper evident",async()=>{const service=await TokenService.create(await config());const ref=await service.serviceRef("https://api.example.com/report");assert.equal(await service.verifyServiceRef(ref),"https://api.example.com/report");const parts=ref.split(".");parts[1]=`${parts[1]![0]==="A"?"B":"A"}${parts[1]!.slice(1)}`;await assert.rejects(()=>service.verifyServiceRef(parts.join(".")));});

test("scheme selection prefers exact, supports upto, and leaves retained limits disabled",async()=>{
  const c=await config();const common={network:BASE_NETWORK,asset:BASE_USDC,payTo:"0x1111111111111111111111111111111111111111",maxTimeoutSeconds:60};const now=Math.floor(Date.now()/1000);const challenge={x402Version:2,resource:{url:"https://api.example.com"},accepts:[{...common,scheme:"auth-capture",amount:"4000000",extra:{name:"USD Coin",version:"2",captureAuthorizer:"0x2222222222222222222222222222222222222222",feeRecipient:"0x3333333333333333333333333333333333333333",captureDeadline:now+3600,refundDeadline:now+7200,minFeeBps:0,maxFeeBps:100}},{...common,scheme:"batch-settlement",amount:"3500000",extra:{receiverAuthorizer:"0x4444444444444444444444444444444444444444"}},{...common,scheme:"upto",amount:"3000000",extra:{facilitatorAddress:"0x5555555555555555555555555555555555555555"}},{...common,scheme:"exact",amount:"2000000",extra:{}}]} as PaymentRequired;
  assert.equal(selectRequirement(challenge,c).scheme,"exact");
  assert.equal(selectRequirement(challenge,c,"upto").amount,"3000000");
  assert.equal(selectRequirement(challenge,c,"batch-settlement").amount,"3500000");
  assert.equal(selectRequirement(challenge,c,"auth-capture").amount,"4000000");
  assert.throws(()=>selectRequirement(challenge,{...c,SPEND_LIMITS_ENABLED:true},"exact"),/per-payment limit/);
});

test("advanced schemes reject malformed server terms before signing",async()=>{
  const c=await config();const common={network:BASE_NETWORK,asset:BASE_USDC,amount:"1000",payTo:"0x1111111111111111111111111111111111111111",maxTimeoutSeconds:60};
  for(const scheme of ["upto","batch-settlement","auth-capture"] as const){const challenge={x402Version:2,resource:{url:"https://api.example.com"},accepts:[{...common,scheme,extra:{}}]} as PaymentRequired;assert.throws(()=>selectRequirement(challenge,c,scheme),/no eligible/);}
});

test("advanced x402 SDK schemes build the expected Base USDC authorization envelopes",async()=>{
  const signatures:unknown[]=[];const signer:ClientEvmSigner={address:"0xaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",signTypedData:async input=>{signatures.push(input);return `0x${"11".repeat(65)}`;}};const common={network:BASE_NETWORK,asset:BASE_USDC,amount:"1000",payTo:"0xbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",maxTimeoutSeconds:60};
  const upto=await new UptoEvmScheme(signer).createPaymentPayload(2,{...common,scheme:"upto",extra:{facilitatorAddress:"0xcccccccccccccccccccccccccccccccccccccccc"}});
  assert.equal((upto.payload as any).permit2Authorization.permitted.amount,"1000");
  const batch=await new BatchSettlementEvmScheme(signer).createPaymentPayload(2,{...common,scheme:"batch-settlement",extra:{name:"USD Coin",version:"2",receiverAuthorizer:"0xdddddddddddddddddddddddddddddddddddddddd",withdrawDelay:900,assetTransferMethod:"eip3009"}});
  assert.equal((batch.payload as any).type,"deposit");assert.equal((batch.payload as any).deposit.amount,"5000");
  const now=Math.floor(Date.now()/1000);const auth=await new AuthCaptureEvmScheme(signer).createPaymentPayload(2,{...common,scheme:"auth-capture",extra:{name:"USD Coin",version:"2",captureAuthorizer:"0xeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee",feeRecipient:"0xffffffffffffffffffffffffffffffffffffffff",captureDeadline:now+3600,refundDeadline:now+7200,minFeeBps:0,maxFeeBps:100,assetTransferMethod:"eip3009"}});
  assert.equal((auth.payload as any).authorization.value,"1000");assert.ok(signatures.length>=4);
});

test("batch channel storage is durable and scoped to the authenticated user",async()=>{
  const calls:unknown[][]=[];const context={balance:"500",chargedCumulativeAmount:"100"};const store={getBatchChannel:async(...args:unknown[])=>{calls.push(["get",...args]);return context;},setBatchChannel:async(...args:unknown[])=>{calls.push(["set",...args]);},deleteBatchChannel:async(...args:unknown[])=>{calls.push(["delete",...args]);}} as unknown as Store;const storage=new PostgresBatchChannelStorage(store,"user-1");
  assert.deepEqual(await storage.get("0xABC"),context);await storage.set("0xABC",context);await storage.delete("0xABC");assert.deepEqual(calls,[["get","user-1","0xABC"],["set","user-1","0xABC",context],["delete","user-1","0xABC"]]);
});

test("resource URL guard rejects SSRF-shaped destinations",()=>{assert.equal(assertSafeResourceUrl("https://api.example.com/path").hostname,"api.example.com");assert.throws(()=>assertSafeResourceUrl("http://api.example.com"));assert.throws(()=>assertSafeResourceUrl("https://127.0.0.1/"));assert.throws(()=>assertSafeResourceUrl("https://169.254.169.254/latest/meta-data"));assert.throws(()=>assertSafeResourceUrl("https://user:pass@example.com"));});

test("resource URL guard rejects non-public IPv4 and IPv6 literals",()=>{
  for(const url of ["https://[::1]/","https://[::ffff:127.0.0.1]/","https://[fd00::1]/","https://[fe80::1]/","https://100.64.0.1/","https://198.18.0.1/"])assert.throws(()=>assertSafeResourceUrl(url),url);
  assert.equal(assertSafeResourceUrl("https://1.1.1.1/resource").hostname,"1.1.1.1");
  assert.equal(assertSafeResourceUrl("https://[2606:4700:4700::1111]/resource").hostname,"[2606:4700:4700::1111]");
});

test("SSRF-safe DNS lookup obeys Node single-address and Undici all-address contracts",async()=>{
  const addresses=[{address:"1.1.1.1",family:4},{address:"2606:4700:4700::1111",family:6}];
  const lookup=createPublicLookup((_hostname,options,callback)=>{assert.deepEqual(options,{all:true,verbatim:true});callback(null,addresses);});
  await new Promise<void>((resolve,reject)=>lookup("api.example.com",{all:true},(error,result)=>{if(error)return reject(error);assert.deepEqual(result,addresses);resolve();}));
  await new Promise<void>((resolve,reject)=>lookup("api.example.com",{},(error,result,family)=>{if(error)return reject(error);assert.equal(result,"1.1.1.1");assert.equal(family,4);resolve();}));
});

test("SSRF-safe DNS lookup rejects the whole resolution when any address is non-public",async()=>{
  const lookup=createPublicLookup((_hostname,_options,callback)=>callback(null,[{address:"1.1.1.1",family:4},{address:"127.0.0.1",family:4}]));
  await assert.rejects(new Promise<void>((resolve,reject)=>lookup("api.example.com",{all:true},error=>error?reject(error):resolve())),/non-public network destinations/);
});

test("response body limit applies before the x402 SDK can buffer a 402 body",async()=>{
  const oversized=new Response(new ReadableStream<Uint8Array>({start(controller){controller.enqueue(new Uint8Array(600_000));controller.enqueue(new Uint8Array(600_000));controller.close();}}),{status:402});
  await assert.rejects(()=>limitResponseBody(oversized,1_000_000).text(),/too large/);
  const declared=new Response("small",{status:402,headers:{"content-length":"1000001"}});
  assert.throws(()=>limitResponseBody(declared,1_000_000),/too large/);
});
