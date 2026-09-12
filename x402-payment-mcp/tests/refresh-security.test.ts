import assert from "node:assert/strict";
import test from "node:test";
import { sha256 } from "../src/security.js";
import { Store } from "../src/store.js";

test("reusing a rotated refresh token revokes its active descendants",async()=>{
  type Row={token_hash:string;user_id:string;client_id:string;scope:string;family_id:string;expires_at:Date;revoked_at:Date|null;used_at:Date|null};
  const rows=new Map<string,Row>();const original="original-refresh-token";rows.set(sha256(original),{token_hash:sha256(original),user_id:"user-1",client_id:"client-1",scope:"x402:pay",family_id:"family-1",expires_at:new Date(Date.now()+60_000),revoked_at:null,used_at:null});
  const client={async query(sql:string,params:unknown[]=[]){
    if(sql==="BEGIN"||sql==="COMMIT"||sql==="ROLLBACK")return{rowCount:null,rows:[]};
    if(sql.startsWith("SELECT user_id")){const row=rows.get(params[0] as string);return{rowCount:row&&row.client_id===params[1]?1:0,rows:row?[row]:[]};}
    if(sql.startsWith("UPDATE refresh_tokens SET used_at")){rows.get(params[0] as string)!.used_at=new Date();return{rowCount:1,rows:[]};}
    if(sql.startsWith("INSERT INTO refresh_tokens")){const [token_hash,user_id,client_id,scope,family_id]=params as string[];rows.set(token_hash!,{token_hash:token_hash!,user_id:user_id!,client_id:client_id!,scope:scope!,family_id:family_id!,expires_at:new Date(Date.now()+60_000),revoked_at:null,used_at:null});return{rowCount:1,rows:[]};}
    if(sql.startsWith("UPDATE refresh_tokens SET revoked_at")){for(const row of rows.values())if(row.family_id===params[0])row.revoked_at??=new Date();return{rowCount:rows.size,rows:[]};}
    throw new Error(`unexpected query: ${sql}`);
  },release(){}};
  const store=Object.create(Store.prototype) as Store;Object.defineProperty(store,"pool",{value:{connect:async()=>client}});
  const rotated=await store.rotateRefreshToken(original,"client-1",3600);assert.ok(rotated);const child=rows.get(sha256(rotated.token));assert.ok(child);assert.equal(child.revoked_at,null);
  assert.equal(await store.rotateRefreshToken(original,"client-1",3600),null);assert.ok(child.revoked_at,"the descendant must be revoked after reuse is detected");
  assert.equal(await store.rotateRefreshToken(rotated.token,"client-1",3600),null);
});
