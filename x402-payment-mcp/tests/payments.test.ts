import assert from "node:assert/strict";
import test from "node:test";
import { requestInit } from "../src/payments.js";

test("a body-less POST builds the same request at preview and after the stored preview round-trip",()=>{
  const atPreview=requestInit({method:"POST"},1000);
  // payment_previews.request_body comes back as null when no body was supplied.
  const atPay=requestInit({method:"POST",body:null},1000);
  for(const init of [atPreview,atPay]){assert.equal(init.body,undefined);assert.equal(init.headers,undefined);assert.equal(init.method,"POST");}
  const withBody=requestInit({method:"POST",body:{q:"btc"}},1000);
  assert.equal(withBody.body,'{"q":"btc"}');assert.deepEqual(withBody.headers,{"content-type":"application/json"});
});

test("payment locks use their own bounded pool so lock holders cannot starve queries",async()=>{
  const {Store,POOL_CONNECT_TIMEOUT_MS}=await import("../src/store.js");
  const store=new Store("postgres://localhost/test");
  try{
    assert.notEqual(store.lockPool,store.pool);
    for(const pool of [store.pool,store.lockPool])assert.equal(pool.options.connectionTimeoutMillis,POOL_CONNECT_TIMEOUT_MS);
    const used:unknown[]=[];const fake={query:async()=>({rows:[]}),release(){}};
    (store.lockPool as any).connect=async()=>{used.push("lock");return fake;};(store.pool as any).connect=async()=>{used.push("main");return fake;};
    assert.equal(await store.withPaymentLock("user-1",async()=>"done"),"done");assert.deepEqual(used,["lock"]);
  }finally{await store.close();}
});

test("an unavailable preview says whether it expired or was already used",async()=>{
  const {previewUnavailableMessage}=await import("../src/store.js");
  assert.match(previewUnavailableMessage({used:true,expired:true}),/already used/);
  assert.match(previewUnavailableMessage({used:false,expired:true}),/expired/);
  assert.match(previewUnavailableMessage(undefined),/not found/);
  const {loadConfig}=await import("../src/config.js");const {exportJWK,generateKeyPair}=await import("jose");
  const {privateKey}=await generateKeyPair("ES256",{extractable:true});
  const config=loadConfig({PUBLIC_BASE_URL:"https://pay.example.com",DATABASE_URL:"postgres://localhost/test",OAUTH_SIGNING_PRIVATE_JWK:JSON.stringify(await exportJWK(privateKey)),GITHUB_CLIENT_ID:"h",GITHUB_CLIENT_SECRET:"h",CDP_API_KEY_ID:"c",CDP_API_KEY_SECRET:"c",CDP_WALLET_SECRET:"c",ARC_RPC_URL:"https://rpc.example.com"});
  assert.equal(config.PREVIEW_TTL_SECONDS,600);
});
