import assert from "node:assert/strict";
import test from "node:test";
import { sha256 } from "../src/security.js";
import { Store } from "../src/store.js";

test("repeated consent approval returns the same PKCE code without minting or resurrecting a grant",async()=>{
  const token="one-time-consent";let approvedAt:Date|null=null;let inserted=0;let codeAvailable=false;
  const pending:{token_hash:string;user_id:string;client_id:string;redirect_uri:string;oauth_state:string;code_challenge:string;resource:string;scope:string;expires_at:Date;approved_at:Date|null}={token_hash:sha256(token),user_id:"user-1",client_id:"client-1",redirect_uri:"https://client.example/callback",oauth_state:"client-state",code_challenge:"challenge",resource:"https://pay.example/mcp",scope:"x402:pay",expires_at:new Date(Date.now()+60_000),approved_at:approvedAt};
  const client={async query(sql:string){
    if(sql==="BEGIN"||sql==="COMMIT"||sql==="ROLLBACK")return{rowCount:null,rows:[]};
    if(sql.startsWith("SELECT * FROM oauth_pending_consents")){pending.approved_at=approvedAt;return{rowCount:1,rows:[pending]};}
    if(sql.startsWith("INSERT INTO oauth_codes")){inserted+=1;codeAvailable=true;return{rowCount:1,rows:[]};}
    if(sql.startsWith("UPDATE oauth_pending_consents")){approvedAt=new Date();return{rowCount:1,rows:[]};}
    throw new Error(`unexpected transaction query: ${sql}`);
  },release(){}};
  const pool={connect:async()=>client,async query(sql:string){
    if(sql.startsWith("DELETE FROM oauth_codes")){if(!codeAvailable)return{rowCount:0,rows:[]};codeAvailable=false;return{rowCount:1,rows:[pending]};}
    throw new Error(`unexpected pool query: ${sql}`);
  }};
  const store=Object.create(Store.prototype) as Store;Object.defineProperty(store,"pool",{value:pool});

  assert.ok(await store.approvePendingConsent(token));
  assert.ok(await store.approvePendingConsent(token));
  assert.equal(inserted,1,"a duplicate browser POST must not create a second authorization code");
  assert.ok(await store.consumeAuthorizationCode(token));
  assert.ok(await store.approvePendingConsent(token),"the browser may still receive the same redirect after code exchange");
  assert.equal(inserted,1,"a consumed authorization code must never be recreated");
  assert.equal(await store.consumeAuthorizationCode(token),null);
});
