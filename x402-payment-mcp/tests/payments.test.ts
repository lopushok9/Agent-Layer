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

test("any public HTTPS url is previewable, with unfilled path templates rejected up front",async()=>{
  const {assertNoPathPlaceholders,findListing}=await import("../src/payments.js");const isListed=(resources:Parameters<typeof findListing>[0],url:string)=>Boolean(findListing(resources,url));
  for(const url of ["https://api.example.com/wallet/:address/portfolio","https://api.example.com/token/{id}","https://api.example.com/token/%7Bid%7D/price"])assert.throws(()=>assertNoPathPlaceholders(url),/placeholder/);
  for(const url of ["https://api.example.com/v1/price","https://api.example.com/v1/price?pair=BTC:USD&tpl={x}","https://api.example.com/a:b/c"])assert.doesNotThrow(()=>assertNoPathPlaceholders(url));
  const accept={scheme:"exact",network:"eip155:8453",asset:"0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913",amount:"1000",payTo:"0x1111111111111111111111111111111111111111",maxTimeoutSeconds:60};
  const resources=[{resource:"https://api.example.com/v1/price-history",accepts:[accept]},{resource:"https://api.example.com/v1/price",accepts:[accept]},{resource:"https://other.example.com/v1/free",accepts:[]}];
  assert.equal(isListed(resources,"https://api.example.com/v1/price?pair=BTC"),true);
  assert.equal(isListed(resources,"https://api.example.com/v1/pric"),false);
  assert.equal(isListed(resources,"https://other.example.com/v1/free"),false);
});

test("the HTTP method comes from the Bazaar hint, then falls back to the other verb on 405",async()=>{
  const {methodCandidates,hintedMethod,preflightFailureMessage}=await import("../src/payments.js");
  assert.deepEqual(methodCandidates(undefined,false),["GET","POST"]);
  assert.deepEqual(methodCandidates(undefined,true),["POST","GET"]);
  assert.deepEqual(methodCandidates("POST",false),["POST","GET"]);
  assert.deepEqual(methodCandidates("DELETE",false),["DELETE"]);
  assert.equal(hintedMethod({bazaar:{info:{input:{method:"post",type:"http"}}}}),"POST");
  assert.equal(hintedMethod({bazaar:{info:{input:{method:"TRACE"}}}}),undefined);
  assert.equal(hintedMethod(undefined),undefined);
  assert.match(preflightFailureMessage(405,"Method Not Allowed","GET"),/\(GET, HTTP 405\)/);
  assert.equal(requestInit({method:"PUT",body:{a:1}},1000).body,'{"a":1}');
  assert.equal(requestInit({method:"GET",body:{a:1}},1000).body,undefined);
});

test("preflight retries the alternate method only on 405 and returns the method that reached the paywall",async()=>{
  const {preflight}=await import("../src/payments.js");const {encodePaymentRequiredHeader}=await import("@x402/core/http");
  const challenge={x402Version:2,resource:{url:"https://api.example.com/run"},accepts:[{scheme:"exact",network:"eip155:8453",asset:"0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913",amount:"1000",payTo:"0x1111111111111111111111111111111111111111",maxTimeoutSeconds:60,extra:{}}]};
  const calls:string[]=[];
  const postOnly=(async(_url:string,init:RequestInit)=>{calls.push(init.method!);return init.method==="POST"?new Response(null,{status:402,headers:{"payment-required":encodePaymentRequiredHeader(challenge as any)}}):new Response("Method Not Allowed",{status:405});}) as unknown as typeof fetch;
  const found=await preflight(postOnly,"https://api.example.com/run",{},["GET","POST"],1000);
  assert.equal(found.method,"POST");assert.equal(found.challenge.accepts[0]!.amount,"1000");assert.deepEqual(calls,["GET","POST"]);
  calls.length=0;
  await assert.rejects(()=>preflight(postOnly,"https://api.example.com/run",{},["GET"],1000),/\(GET, HTTP 405\)/);
  const badRequest=(async(_url:string,init:RequestInit)=>{calls.push(init.method!);return new Response('{"error":"missing a"}',{status:400,headers:{"content-type":"application/json"}});}) as unknown as typeof fetch;
  calls.length=0;await assert.rejects(()=>preflight(badRequest,"https://api.example.com/run",{},["GET","POST"],1000),/HTTP 400.*missing a/);assert.deepEqual(calls,["GET"]);
});

test("caller headers and a raw text body reach the provider, while transport and payment headers stay reserved",async()=>{
  const {normalizeRequestHeaders}=await import("../src/payments.js");
  assert.deepEqual(normalizeRequestHeaders({"Accept":"text/csv","X-Client":"agent"}),{accept:"text/csv","x-client":"agent"});
  assert.equal(normalizeRequestHeaders({}),undefined);
  for(const name of ["Host","content-length","PAYMENT-SIGNATURE","X-Payment","Proxy-Connection"])assert.throws(()=>normalizeRequestHeaders({[name]:"x"}),/cannot be set/);
  assert.throws(()=>normalizeRequestHeaders({"bad name":"x"}),/invalid header name/);
  assert.throws(()=>normalizeRequestHeaders({"x-a":"line\r\nInjected: 1"}),/invalid value/);
  const text=requestInit({method:"POST",headers:{"content-type":"text/plain"},textBody:"raw payload"},1000);
  assert.equal(text.body,"raw payload");assert.deepEqual(text.headers,{"content-type":"text/plain"});
  const json=requestInit({method:"POST",headers:{"content-type":"application/vnd.api+json"},body:{a:1}},1000);
  assert.deepEqual(json.headers,{"content-type":"application/vnd.api+json"});
  assert.equal(requestInit({method:"GET",textBody:"ignored"},1000).body,undefined);
});

test("preflight follows safe redirects and binds the preview to the final url",async()=>{
  const {preflight}=await import("../src/payments.js");const {encodePaymentRequiredHeader}=await import("@x402/core/http");
  const paywall=()=>new Response(null,{status:402,headers:{"payment-required":encodePaymentRequiredHeader({x402Version:2,resource:{url:"https://api.example.com/v2/run"},accepts:[{scheme:"exact",network:"eip155:8453",asset:"0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913",amount:"1000",payTo:"0x1111111111111111111111111111111111111111",maxTimeoutSeconds:60,extra:{}}]} as any)}});
  const redirect=(status:number,location:string)=>new Response(null,{status,headers:{location}});
  const server=(routes:Record<string,()=>Response>)=>{const seen:string[]=[];return{seen,fetch:(async(url:string)=>{seen.push(url);return (routes[url]??(()=>new Response("nope",{status:404})))();}) as unknown as typeof fetch};};
  const moved=server({"https://api.example.com/run":()=>redirect(301,"/v2/run"),"https://api.example.com/v2/run":paywall});
  const found=await preflight(moved.fetch,"https://api.example.com/run",{},["GET"],1000);
  assert.equal(found.url,"https://api.example.com/v2/run");assert.deepEqual(moved.seen,["https://api.example.com/run","https://api.example.com/v2/run"]);
  const internal=server({"https://api.example.com/run":()=>redirect(302,"https://169.254.169.254/latest/meta-data")});
  await assert.rejects(()=>preflight(internal.fetch,"https://api.example.com/run",{},["GET"],1000),/non-public/);
  const downgrade=server({"https://api.example.com/run":()=>redirect(302,"http://api.example.com/run")});
  await assert.rejects(()=>preflight(downgrade.fetch,"https://api.example.com/run",{},["GET"],1000),/HTTPS/);
  const postMoved=server({"https://api.example.com/run":()=>redirect(302,"/v2/run"),"https://api.example.com/v2/run":paywall});
  await assert.rejects(()=>preflight(postMoved.fetch,"https://api.example.com/run",{body:{a:1}},["POST"],1000),/would change the method/);
  const postKept=server({"https://api.example.com/run":()=>redirect(308,"/v2/run"),"https://api.example.com/v2/run":paywall});
  assert.equal((await preflight(postKept.fetch,"https://api.example.com/run",{body:{a:1}},["POST"],1000)).url,"https://api.example.com/v2/run");
  const otherHost=server({"https://api.example.com/run":()=>redirect(307,"https://cdn.example.net/run")});
  await assert.rejects(()=>preflight(otherHost.fetch,"https://api.example.com/run",{headers:{accept:"text/csv"}},["GET"],1000),/another host/);
  const loop=server({"https://api.example.com/run":()=>redirect(302,"/run")});
  await assert.rejects(()=>preflight(loop.fetch,"https://api.example.com/run",{},["GET"],1000),/more than 5 times/);
});
