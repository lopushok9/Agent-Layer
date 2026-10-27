import assert from "node:assert/strict";
import test from "node:test";
import { randomBytes, randomUUID } from "node:crypto";
import { getAddress } from "viem";
import { Store } from "../src/store.js";
import { WalletStore, type SmartWalletRecord } from "../src/wallet-store.js";
import { SmartWalletService } from "../src/smart-wallet.js";
function wallet(): SmartWalletRecord {
  const id=randomUUID();
  return {ownerName:`owner-${id}`,accountName:`smart-${id}`,ownerAddress:getAddress(`0x${randomBytes(20).toString("hex")}`),address:getAddress(`0x${randomBytes(20).toString("hex")}`)};
}
test("Postgres: replacement archives the old wallet without resetting its unknown operation; only the new address is unblocked", {skip:!process.env.TEST_DATABASE_URL},async()=>{
  const db=new Store(process.env.TEST_DATABASE_URL!);
  try{
    await db.migrate();await db.migrate();
    const store=new WalletStore(db.pool), old=wallet(), next=wallet();
    const user=await db.upsertIdentity("github",randomUUID(),null,null), other=await db.upsertIdentity("github",randomUUID(),null,null);
    await store.saveWallet(user,old);
    const make=(address:typeof old.address)=>store.createOperation({userId:user,network:"base",address,calls:[],descriptions:[],fingerprint:"test",simulation:{}},600);
    const pending=await make(old.address);
    await store.reserve(user,pending.id,"old operation");
    const hash=`0x${"1".repeat(64)}` as const;
    await store.beforeSigning(pending.id,hash);await store.finish(pending.id,"unknown");
    const request=randomUUID();
    await db.withPaymentLock(user,()=>store.replaceWallet(user,old.address,next,request,"User requested a fresh test wallet"));
    assert.deepEqual(await store.wallet(user),next);
    assert.deepEqual(await store.walletByAddress(user,old.address),old);
    assert.equal(await store.walletByAddress(other,old.address),null);
    assert.equal((await store.operation(user,pending.id))!.status,"unknown");
    assert.equal((await store.operation(user,pending.id))!.userOpHash,hash);
    const archivedPreview=await make(old.address);
    await assert.rejects(store.reserve(user,archivedPreview.id,"old still blocked"),/unresolved/);
    const fresh=await make(next.address);
    assert.equal((await store.reserve(user,fresh.id,"new wallet"))!.status,"reserved");
    const duplicate=await make(next.address);
    await assert.rejects(store.reserve(user,duplicate.id,"new still protected"),/unresolved/);
    await store.replaceWallet(user,old.address,next,request,"idempotent retry");
    await assert.rejects(store.replaceWallet(user,old.address,wallet(),randomUUID(),"stale request"),/active wallet changed/);
    await assert.rejects(store.replaceWallet(other,old.address,wallet(),request,"wrong user"),/not found/);
    const count=await db.pool.query("SELECT count(*)::int n FROM smart_wallet_history WHERE user_id=$1",[user]);
    assert.equal(count.rows[0].n,1);
    // Legacy status must query the archived smart address, never the new one.
    let queried="";
    const service=new SmartWalletService({} as any,store,{evm:{getUserOperation:async({smartAccount}:any)=>{queried=smartAccount;return{status:"signed"};}}} as any);
    assert.equal((await service.operation(user,hash,old.address)).status,"signed");assert.equal(queried,old.address);
    await assert.rejects(service.operation(other,hash,old.address),/not registered/);
    assert.equal((await store.operation(user,pending.id))!.status,"unknown");
  }finally{await db.close();}
});
