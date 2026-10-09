import assert from "node:assert/strict";
import test from "node:test";
import { InMemoryTransport } from "@modelcontextprotocol/server";
import { createUserMcp, INSTRUCTIONS, LINK_INSTRUCTIONS } from "../src/mcp.js";

// Drives the real MCP server over JSON-RPC so the published schemas and argument handling are what a host actually sees.
async function connect(payments:Record<string,(...args:any[])=>unknown>,link:Record<string,(...args:any[])=>unknown>|null=null){
  const [client,server]=InMemoryTransport.createLinkedPair();const pending=new Map<number,(value:any)=>void>();let id=0;
  client.onmessage=(message:any)=>{pending.get(message.id)?.(message);pending.delete(message.id);};
  await createUserMcp("user-1",payments as any,{} as any,link as any).connect(server);await client.start();
  const request=(method:string,params:unknown={})=>new Promise<any>(resolve=>{const n=++id;pending.set(n,resolve);void client.send({jsonrpc:"2.0",id:n,method,params} as any);});
  const init=await request("initialize",{protocolVersion:"2025-06-18",capabilities:{},clientInfo:{name:"test",version:"0"}});
  await client.send({jsonrpc:"2.0",method:"notifications/initialized"} as any);
  return{init,request,call:(name:string,args:unknown)=>request("tools/call",{name,arguments:args})};
}

test("the server publishes its workflow and a url-based preview schema",async()=>{
  const {init,request}=await connect({});
  assert.equal(init.result.instructions,INSTRUCTIONS);assert.match(INSTRUCTIONS,/x402_preview/);
  const tools=(await request("tools/list")).result.tools as {name:string;inputSchema:any}[];
  const preview=tools.find(t=>t.name==="x402_preview")!.inputSchema;
  assert.equal(preview.additionalProperties,false);assert.deepEqual(preview.required??[],[]);
  for(const key of ["url","service_ref","method","query","headers","body","text_body","scheme"])assert.ok(preview.properties[key],key);
  assert.deepEqual(preview.properties.method.enum,["GET","POST","PUT","PATCH","DELETE"]);
  assert.deepEqual(tools.find(t=>t.name==="x402_search")!.inputSchema.properties.provider.enum,["bazaar","agentic_market"]);
});

test("x402_preview forwards a plain url request and rejects ambiguous or unknown arguments",async()=>{
  const seen:unknown[][]=[];const {call}=await connect({preview:async(...args:unknown[])=>{seen.push(args);return{preview_id:"p"};}});
  const ok=await call("x402_preview",{url:"https://api.example.com/run",query:{a:"BTC"},headers:{accept:"text/csv"},text_body:"raw"});
  assert.equal(ok.result.isError,undefined);
  assert.deepEqual(seen,[["user-1",{url:"https://api.example.com/run"},{query:{a:"BTC"},headers:{accept:"text/csv"},textBody:"raw"},"auto"]]);
  await call("x402_preview",{service_ref:"x".repeat(40),method:"POST",body:{q:1}});
  assert.deepEqual(seen[1],["user-1",{serviceRef:"x".repeat(40)},{method:"POST",body:{q:1}},"auto"]);
  for(const bad of [{},{url:"https://api.example.com/run",service_ref:"x".repeat(40)},{url:"https://api.example.com/run",params:{a:"BTC"}},{url:"https://api.example.com/run",body:{a:1},text_body:"raw"},{url:"not a url"}]){
    const result=await call("x402_preview",bad);assert.ok(result.error||result.result.isError,JSON.stringify(bad));
  }
  assert.equal(seen.length,2);
});

test("a tool failure reaches the agent as an error with the reason",async()=>{
  const {call}=await connect({pay:async()=>{throw new Error("payment was not made: preview expired before payment. Nothing was signed or charged; call x402_preview again to retry");}});
  const original=console.error;console.error=()=>{};
  try{const result=await call("x402_pay",{preview_id:"3f0a3c2e-6f0b-4c53-9f4e-0d3a1a2b3c4d",purpose:"test purchase"});assert.equal(result.result.isError,true);assert.match(result.result.content[0].text,/Nothing was signed or charged/);}finally{console.error=original;}
});

test("Link tools appear only when Link is configured, always request approval, and validate purchases",async()=>{
  const plain=await connect({});const plainTools=(await plain.request("tools/list")).result.tools as {name:string}[];
  assert.equal(plainTools.some(t=>t.name.startsWith("link_")),false);assert.equal(plain.init.result.instructions,INSTRUCTIONS);
  const seen:unknown[][]=[];const {init,request,call}=await connect({},{createSpendRequest:async(...args:unknown[])=>{seen.push(args);return{id:"lsrq_1",approval_url:"https://app.link.com/a"};}});
  assert.equal(init.result.instructions,INSTRUCTIONS+LINK_INSTRUCTIONS);
  const names=((await request("tools/list")).result.tools as {name:string}[]).map(t=>t.name).filter(n=>n.startsWith("link_")).sort();
  assert.deepEqual(names,["link_cancel_spend_request","link_connect","link_create_spend_request","link_disconnect","link_get_pay_token","link_get_spend_request","link_shipping_addresses","link_status","link_update_spend_request"]);
  const base={amount:3500,context:"Purchasing 'Working in Public' from press.stripe.com because the user asked the assistant to buy this book for them today.",idempotency_key:"purchase-1"};
  const ok=await call("link_create_spend_request",{...base,merchant_name:"Stripe Press",merchant_url:"https://press.stripe.com"});
  assert.equal(ok.result.isError,undefined);assert.equal((seen[0]![1] as any).credential_type,"card");assert.equal((seen[0]![1] as any).currency,"usd");
  for(const bad of [{...base},{...base,merchant_name:"M",merchant_url:"http://insecure.example"},{...base,context:"too short",merchant_name:"M",merchant_url:"https://m.example"},{...base,credential_type:"link_pay_token"},{...base,credential_type:"shared_payment_token",merchant_name:"M",merchant_url:"https://m.example"},{...base,merchant_name:"M",merchant_url:"https://m.example",request_approval:false}]){
    const r=await call("link_create_spend_request",bad);assert.ok(r.result?.isError||r.error,JSON.stringify(bad));
  }
  assert.equal(seen.length,1,"invalid purchases never reach Link");
});
