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

test("preflight tries the alternate method on a client error and returns the method that reached the paywall",async()=>{
  const {preflight}=await import("../src/payments.js");const {encodePaymentRequiredHeader}=await import("@x402/core/http");
  const challenge={x402Version:2,resource:{url:"https://api.example.com/run"},accepts:[{scheme:"exact",network:"eip155:8453",asset:"0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913",amount:"1000",payTo:"0x1111111111111111111111111111111111111111",maxTimeoutSeconds:60,extra:{}}]};
  const calls:string[]=[];
  const postOnly=(async(_url:string,init:RequestInit)=>{calls.push(init.method!);return init.method==="POST"?new Response(null,{status:402,headers:{"payment-required":encodePaymentRequiredHeader(challenge as any)}}):new Response("Method Not Allowed",{status:405});}) as unknown as typeof fetch;
  const found=await preflight(postOnly,"https://api.example.com/run",{},["GET","POST"],1000);
  assert.equal(found.method,"POST");assert.equal(found.challenge.accepts[0]!.amount,"1000");assert.deepEqual(calls,["GET","POST"]);
  calls.length=0;
  await assert.rejects(()=>preflight(postOnly,"https://api.example.com/run",{},["GET"],1000),/\(GET, HTTP 405\)/);
  const badRequest=(async(_url:string,init:RequestInit)=>{calls.push(init.method!);return new Response('{"error":"missing a"}',{status:400,headers:{"content-type":"application/json"}});}) as unknown as typeof fetch;
  calls.length=0;await assert.rejects(()=>preflight(badRequest,"https://api.example.com/run",{},["GET","POST"],1000),/\(GET, HTTP 400\).*missing a/);assert.deepEqual(calls,["GET","POST"]);
  // Seen in the Bazaar: the wrong verb answers 404, 401, or a 402 with no challenge instead of 405.
  for(const wrongVerb of [()=>new Response("not found",{status:404}),()=>new Response("unauthorized",{status:401}),()=>new Response('{"error":"Payment Required or Discovery Needed"}',{status:402})]){
    const provider=(async(_url:string,init:RequestInit)=>init.method==="POST"?new Response(null,{status:402,headers:{"payment-required":encodePaymentRequiredHeader(challenge as any)}}):wrongVerb()) as unknown as typeof fetch;
    assert.equal((await preflight(provider,"https://api.example.com/run",{},["GET","POST"],1000)).method,"POST");
  }
  const noChallenge=(async()=>new Response("{}",{status:402})) as unknown as typeof fetch;
  await assert.rejects(()=>preflight(noChallenge,"https://api.example.com/run",{},["GET","POST"],1000),/402 without PAYMENT-REQUIRED \(GET\)/);
  const down=(async(_url:string,init:RequestInit)=>{calls.push(init.method!);return new Response("bad gateway",{status:502});}) as unknown as typeof fetch;
  calls.length=0;await assert.rejects(()=>preflight(down,"https://api.example.com/run",{},["GET","POST"],1000),/HTTP 502/);assert.deepEqual(calls,["GET"]);
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

async function exactClient(){
  const {x402Client}=await import("@x402/core/client");const {registerExactEvmScheme}=await import("@x402/evm/exact/client");const {generatePrivateKey,privateKeyToAccount}=await import("viem/accounts");
  const account=privateKeyToAccount(generatePrivateKey());const client=new x402Client();registerExactEvmScheme(client,{signer:account as any,networks:["eip155:8453"]});return{client,account};
}
const paidChallenge={x402Version:2,resource:{url:"https://api.example.com/run"},accepts:[{scheme:"exact",network:"eip155:8453",asset:"0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913",amount:"25000",payTo:"0x1111111111111111111111111111111111111111",maxTimeoutSeconds:60,extra:{name:"USD Coin",version:"2"}}]} as any;

test("paying signs the previewed challenge and sends exactly one paid request with its own timeout",async()=>{
  const {payStoredChallenge}=await import("../src/payments.js");const {decodePaymentSignatureHeader,encodePaymentResponseHeader}=await import("@x402/core/http");
  const {client,account}=await exactClient();let signedCount=0;client.onAfterPaymentCreation(async()=>{signedCount++;});
  const calls:{url:string;init:RequestInit}[]=[];
  const provider=(async(url:string,init:RequestInit)=>{calls.push({url,init});return new Response('{"ok":true}',{status:200,headers:{"content-type":"application/json","payment-response":encodePaymentResponseHeader({success:true,transaction:"0xabc",network:"eip155:8453",payer:account.address} as any)}});}) as unknown as typeof fetch;
  const {response,paid}=await payStoredChallenge({client,fetchImpl:provider,url:"https://api.example.com/run?a=BTC",request:{method:"POST",headers:{accept:"application/json"},body:{q:"btc"}},paymentRequired:paidChallenge,timeout:1000});
  assert.equal(response.status,200);assert.equal(paid,true);assert.equal(calls.length,1);assert.equal(signedCount,1);
  const {url,init}=calls[0]!;const headers=init.headers as Record<string,string>;
  assert.equal(url,"https://api.example.com/run?a=BTC");assert.equal(init.method,"POST");assert.equal(init.body,'{"q":"btc"}');assert.equal(headers.accept,"application/json");assert.ok(init.signal instanceof AbortSignal);
  const payload=decodePaymentSignatureHeader(headers["PAYMENT-SIGNATURE"]!) as any;
  assert.equal(payload.accepted.amount,"25000");assert.equal(payload.accepted.payTo,"0x1111111111111111111111111111111111111111");
  assert.equal(payload.payload.authorization.from.toLowerCase(),account.address.toLowerCase());assert.equal(payload.payload.authorization.value,"25000");
});

test("a refused or unsettled paid request reports the provider's reason",async()=>{
  const {payStoredChallenge,unsettledReason}=await import("../src/payments.js");const {encodePaymentRequiredHeader}=await import("@x402/core/http");const {limitedBody}=await import("../src/network.js");
  const {client}=await exactClient();
  const refusing=(async()=>new Response("{}",{status:402,headers:{"content-type":"application/json","payment-required":encodePaymentRequiredHeader({...paidChallenge,error:"insufficient_funds"})}})) as unknown as typeof fetch;
  const {response:refused}=await payStoredChallenge({client,fetchImpl:refusing,url:"https://api.example.com/run",request:{method:"GET"},paymentRequired:paidChallenge,timeout:1000});
  assert.equal(refused.status,402);
  assert.match(unsettledReason(refused,await limitedBody(refused)),/refused the signed payment.*insufficient_funds/);
  assert.match(unsettledReason(new Response("upstream down",{status:502}),"upstream down"),/HTTP 502.*upstream down/);
  assert.match(unsettledReason(new Response("{}",{status:200}),null),/without reporting a settlement/);
  const hanging=((_url:string,init:RequestInit)=>new Promise((_resolve,reject)=>init.signal!.addEventListener("abort",()=>reject(init.signal!.reason)))) as unknown as typeof fetch;
  // AbortSignal.timeout does not keep the event loop alive on its own.
  const keepAlive=setTimeout(()=>{},2000);
  try{await assert.rejects(()=>payStoredChallenge({client,fetchImpl:hanging,url:"https://api.example.com/run",request:{method:"GET"},paymentRequired:paidChallenge,timeout:50}),/timeout|aborted/i);}finally{clearTimeout(keepAlive);}
});

test("Sign-In-With-X is attached when the provider declares it, and granted access is not charged",async()=>{
  const {payStoredChallenge}=await import("../src/payments.js");const {encodePaymentResponseHeader}=await import("@x402/core/http");
  const {buildSIWxSchema,createSIWxClientExtension,parseSIWxHeader,SIGN_IN_WITH_X}=await import("@x402/extensions/sign-in-with-x");
  const declared={...paidChallenge,extensions:{[SIGN_IN_WITH_X]:{info:{domain:"api.example.com",uri:"https://api.example.com/run",version:"1",nonce:"abcdef1234567890",issuedAt:new Date().toISOString(),expirationTime:new Date(Date.now()+300_000).toISOString()},supportedChains:[{chainId:"eip155:8453",type:"eip191"}],schema:buildSIWxSchema()}}};
  const make=async()=>{const {client,account}=await exactClient();client.registerExtension(createSIWxClientExtension({signers:[account as any]}));let signed=0;client.onAfterPaymentCreation(async()=>{signed++;});return{client,account,signed:()=>signed};};
  const settledHeaders=(payer:string)=>({"payment-response":encodePaymentResponseHeader({success:true,transaction:"0xabc",network:"eip155:8453",payer} as any)});

  const returning=await make();const seen:Record<string,string>[]=[];
  const knowsWallet=(async(_url:string,init:RequestInit)=>{seen.push(init.headers as Record<string,string>);return new Response("cached report",{status:200});}) as unknown as typeof fetch;
  const granted=await payStoredChallenge({client:returning.client,fetchImpl:knowsWallet,url:"https://api.example.com/run",request:{method:"GET"},paymentRequired:declared,timeout:1000});
  assert.equal(granted.paid,false);assert.equal(returning.signed(),0);assert.equal(seen.length,1);assert.equal(seen[0]!["PAYMENT-SIGNATURE"],undefined);
  assert.equal((parseSIWxHeader(seen[0]![SIGN_IN_WITH_X]!) as any).address,returning.account.address);

  const first=await make();const requests:Record<string,string>[]=[];
  const needsPayment=(async(_url:string,init:RequestInit)=>{const headers=init.headers as Record<string,string>;requests.push(headers);return headers["PAYMENT-SIGNATURE"]?new Response("report",{status:200,headers:settledHeaders(first.account.address)}):new Response(null,{status:402});}) as unknown as typeof fetch;
  const charged=await payStoredChallenge({client:first.client,fetchImpl:needsPayment,url:"https://api.example.com/run",request:{method:"GET"},paymentRequired:declared,timeout:1000});
  assert.equal(charged.paid,true);assert.equal(first.signed(),1);assert.equal(requests.length,2);assert.ok(requests[1]![SIGN_IN_WITH_X]);assert.ok(requests[1]!["PAYMENT-SIGNATURE"]);

  const plain=await make();const plainRequests:Record<string,string>[]=[];
  const noSignIn=(async(_url:string,init:RequestInit)=>{plainRequests.push(init.headers as Record<string,string>);return new Response("report",{status:200,headers:settledHeaders(plain.account.address)});}) as unknown as typeof fetch;
  await payStoredChallenge({client:plain.client,fetchImpl:noSignIn,url:"https://api.example.com/run",request:{method:"GET"},paymentRequired:paidChallenge,timeout:1000});
  assert.equal(plainRequests.length,1);assert.equal(plainRequests[0]![SIGN_IN_WITH_X],undefined);
});

test("Agentic Market results list only Base USDC endpoints with a previewable url",async()=>{
  const {agenticMarketResources}=await import("../src/payments.js");
  const payload={services:[{name:"ChainQuery",description:"Bitcoin intelligence",endpoints:[
    {url:"https://intel.example.com/v1/velocity",description:"Coin velocity",method:"get",serviceName:"ChainQuery Bitcoin Intelligence",pricing:{amount:"0.01",currency:"USDC",network:"eip155:8453",scheme:"exact"}},
    {url:"https://intel.example.com/v1/solana",method:"GET",pricing:{amount:"0.01",currency:"USDC",network:"solana:5eykt4UsFv8P8NJdTREpY1vzqKqZKvdp"}},
    {url:"http://intel.example.com/v1/plain",method:"GET",pricing:{amount:"0.01",currency:"USDC",network:"Base"}},
    {url:"https://intel.example.com/v1/run",method:"POST",pricing:{amount:"0.5",currency:"usdc",network:"Base"}}]},
    {name:"Broken",endpoints:"none"},"junk"]};
  const resources=agenticMarketResources(payload,10);
  assert.deepEqual(resources.map(r=>[r.url,r.method,r.price_usdc]),[["https://intel.example.com/v1/velocity","GET","0.01"],["https://intel.example.com/v1/run","POST","0.5"]]);
  assert.equal(resources[0]!.service_name,"ChainQuery Bitcoin Intelligence");assert.equal(resources[1]!.description,"Bitcoin intelligence");
  assert.equal(agenticMarketResources(payload,1).length,1);assert.deepEqual(agenticMarketResources({error:"x"},10),[]);
});

test("an unpaid probe retries one transient connection error and names the cause when unreachable",async()=>{
  const {preflight}=await import("../src/payments.js");const {encodePaymentRequiredHeader}=await import("@x402/core/http");
  const reset=()=>Object.assign(new TypeError("fetch failed"),{cause:{code:"ECONNRESET",message:"socket disconnected"}});
  let calls=0;const flaky=(async()=>{if(++calls===1)throw reset();return new Response(null,{status:402,headers:{"payment-required":encodePaymentRequiredHeader(paidChallenge)}});}) as unknown as typeof fetch;
  assert.equal((await preflight(flaky,"https://api.example.com/run",{},["GET"],1000)).method,"GET");assert.equal(calls,2);
  calls=0;const dead=(async()=>{calls++;throw reset();}) as unknown as typeof fetch;
  await assert.rejects(()=>preflight(dead,"https://api.example.com/run",{},["GET","POST"],1000),/could not reach the resource before payment: ECONNRESET socket disconnected/);assert.equal(calls,2);
  const slow=(async()=>{throw Object.assign(new Error("The operation was aborted due to timeout"),{name:"TimeoutError"});}) as unknown as typeof fetch;
  await assert.rejects(()=>preflight(slow,"https://api.example.com/run",{},["GET"],1000),/no response within 1000 ms/);
});

test("a settled payment stays settled when the paid response body cannot be read",async()=>{
  const {readResult}=await import("../src/payments.js");const {limitResponseBody}=await import("../src/network.js");const {encodePaymentResponseHeader}=await import("@x402/core/http");
  const settlement=encodePaymentResponseHeader({success:true,transaction:"0xabc",network:"eip155:8453",payer:"0x1111111111111111111111111111111111111111"} as any);
  const oversized=limitResponseBody(new Response("x",{status:200,headers:{"content-length":"5000000","payment-response":settlement}}));
  assert.equal(oversized.status,200);assert.equal(oversized.headers.get("payment-response"),settlement);
  assert.match((await readResult(oversized) as {result_unavailable:string}).result_unavailable,/too large/);
  assert.deepEqual(await readResult(new Response('{"ok":true}',{headers:{"content-type":"application/json"}})),{ok:true});
});
