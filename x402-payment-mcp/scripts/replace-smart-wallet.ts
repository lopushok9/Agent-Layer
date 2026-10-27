// Operator-only replacement, explicitly authorized by the affected user. Does
// not sign, send transactions, move funds, alter grants or reset old operations.
import { createHash } from "node:crypto";
import { getAddress } from "viem";
import { z } from "zod";
import { CdpClient } from "@coinbase/cdp-sdk";
import { loadConfig } from "../src/config.js";
import { Store } from "../src/store.js";
import { WalletStore } from "../src/wallet-store.js";
import { SmartWalletService } from "../src/smart-wallet.js";
import { coinbaseAccount } from "../src/alchemy-executor.js";
const input = z.strictObject({ old_address: z.string().transform(v=>getAddress(v)), request_id: z.string().uuid() }).parse(JSON.parse(await new Promise<string>((resolve, reject) => { let raw="";process.stdin.setEncoding("utf8");process.stdin.on("data",x=>{raw+=x;if(raw.length>4096)reject(new Error("input too large"));});process.stdin.on("end",()=>resolve(raw));process.stdin.on("error",reject); })));
const config=loadConfig(), store=new Store(config.DATABASE_URL), wallets=new WalletStore(store.pool,config.WALLET_OPERATION_ENCRYPTION_KEY);
try {
  // Production startup applies the idempotent migration before this operator
  // script is run. Never migrate or modify unrelated records here.
  const r=await store.pool.query(`SELECT user_id FROM smart_wallets WHERE lower(address)=lower($1)
    UNION SELECT user_id FROM smart_wallet_history WHERE lower(address)=lower($1) AND replacement_request_id=$2`,[input.old_address,input.request_id]);
  if(r.rowCount!==1)throw new Error("Expected exactly one wallet owner");
  const userId=r.rows[0].user_id as string;
  await store.withPaymentLock(userId,async()=>{
    const current=await wallets.wallet(userId);
    if(!current)throw new Error("Wallet registry missing");
    const suffix=createHash("sha256").update(`wallet-replacement:${userId}:${input.request_id}`).digest("hex").slice(0,24);
    const ownerName=`owner-r-${suffix}`, accountName=`smart-r-${suffix}`;
    if(current.address.toLowerCase()!==input.old_address.toLowerCase()&&current.accountName!==accountName)throw new Error("Active wallet changed before replacement");
    const cdp=new CdpClient({apiKeyId:config.CDP_API_KEY_ID,apiKeySecret:config.CDP_API_KEY_SECRET,walletSecret:config.CDP_WALLET_SECRET});
    const owner=await cdp.evm.getOrCreateAccount({name:ownerName});
    const account=await cdp.evm.getOrCreateSmartAccount({name:accountName,owner});
    const service=new SmartWalletService(config,wallets,cdp);
    await coinbaseAccount(service.rpc("base"),account,"base");
    await coinbaseAccount(service.rpc("ethereum"),account,"ethereum");
    await wallets.replaceWallet(userId,input.old_address,{ownerName,ownerAddress:owner.address,accountName,address:account.address},input.request_id,"User explicitly requested a fresh smart account after unresolved legacy CDP operation; no funds moved.");
    console.log(JSON.stringify({old_address:input.old_address,new_address:account.address,request_id:input.request_id,old_wallet_archived:true,funds_moved:false,transactions_sent:false}));
  });
} catch { console.error("Wallet replacement failed. Provider and credential details suppressed. Retry only with the same request_id after checking registry state.");process.exitCode=1; }
finally { await store.close(); }
