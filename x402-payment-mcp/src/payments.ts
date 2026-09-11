import { createHash } from "node:crypto";
import { CdpClient, searchX402Resources } from "@coinbase/cdp-sdk";
import { fromCdpEvmAccount } from "@coinbase/cdp-sdk/x402";
import { x402Client } from "@x402/core/client";
import { decodePaymentRequiredHeader } from "@x402/core/http";
import type { PaymentRequired, PaymentRequirements } from "@x402/core/types";
import { registerExactEvmScheme } from "@x402/evm/exact/client";
import { wrapFetchWithPayment } from "@x402/fetch";
import { BASE_NETWORK, BASE_USDC, type Config } from "./config.js";
import { assertSafeResourceUrl, limitedBody, safeFetch } from "./network.js";
import { TokenService } from "./security.js";
import { Store } from "./store.js";

export type RequestSpec={method:"GET"|"POST";body?:unknown};

export class PaymentService{
  private readonly cdp:CdpClient;
  constructor(private config:Config,private store:Store,private tokens:TokenService){this.cdp=new CdpClient({apiKeyId:config.CDP_API_KEY_ID,apiKeySecret:config.CDP_API_KEY_SECRET,walletSecret:config.CDP_WALLET_SECRET});}

  async search(query:string,limit:number){const found=await searchX402Resources({query:query.slice(0,400),network:BASE_NETWORK,asset:BASE_USDC,scheme:"exact",maxUsdPrice:atomicUsd(this.config.MAX_PAYMENT_USDC_ATOMIC)});const resources=await Promise.all(found.resources.slice(0,limit).map(async r=>{const accepts=(r.accepts??[]).filter(isAllowedLike) as unknown as RequirementLike[];return{service_ref:await this.tokens.serviceRef(r.resource),service_name:r.serviceName,description:r.description,type:r.type,accepts:accepts.map(publicRequirementLike),quality:r.quality,tags:r.tags};}));return{resources,partial_results:found.partialResults,search_method:found.searchMethod};}

  async walletStatus(userId:string){const account=await this.account(userId);const scoped=await account.useNetwork("base");const result=await scoped.listTokenBalances({pageSize:100});const usdc=result.balances.find(b=>b.token.contractAddress.toLowerCase()===BASE_USDC);return{network:BASE_NETWORK,address:account.address,usdc_atomic:usdc?.amount.amount.toString()??"0",usdc_decimals:usdc?.amount.decimals??6,per_payment_limit_atomic:this.config.MAX_PAYMENT_USDC_ATOMIC,daily_limit_atomic:this.config.MAX_DAILY_USDC_ATOMIC};}

  async preview(userId:string,serviceRef:string,spec:RequestSpec){const url=await this.resolveRef(serviceRef);const challenge=await this.preflight(url,spec);const selected=selectRequirement(challenge,this.config);const fingerprint=requirementFingerprint(challenge,selected,url,spec);const saved=await this.store.createPreview({userId,method:spec.method,url,body:spec.body??null,fingerprint,amount:selected.amount,payTo:selected.payTo},this.config.PREVIEW_TTL_SECONDS);return{preview_id:saved.id,expires_at:saved.expiresAt.toISOString(),resource:{url,description:challenge.resource.description,service_name:challenge.resource.serviceName},payment:publicRequirement(selected),request:{method:spec.method,has_body:spec.body!==undefined}};}

  async pay(userId:string,previewId:string,purpose:string){const reserved=await this.store.reservePayment(userId,previewId,BigInt(this.config.MAX_DAILY_USDC_ATOMIC),purpose);if(!reserved)throw new Error("preview is expired, already used, or does not belong to this user");const {paymentId,preview}=reserved;let signed=false;
    try{const account=await this.account(userId);const signer=fromCdpEvmAccount(account);const client=new x402Client();client.setSpendControls({maxAmountPerPayment:`$${atomicUsd(this.config.MAX_PAYMENT_USDC_ATOMIC)}`,allowedAssets:[]});registerExactEvmScheme(client,{signer,networks:[BASE_NETWORK]});client.registerPolicy((_v,reqs)=>reqs.filter(isAllowed));client.onBeforePaymentCreation(async({paymentRequired,selectedRequirements})=>{const now=requirementFingerprint(paymentRequired,selectedRequirements,preview.url,{method:preview.method as "GET"|"POST",body:preview.body});if(now!==preview.fingerprint)return{abort:true,reason:"payment terms changed since preview"};signed=true;});
      const paidFetch=wrapFetchWithPayment(safeFetch,client);const response=await paidFetch(preview.url,requestInit({method:preview.method as "GET"|"POST",body:preview.body},this.config.PAYMENT_TIMEOUT_MS));const body=await limitedBody(response);const settlement=decodeSettlement(response);const settled=response.ok&&settlement?.success===true;await this.store.finishPayment(paymentId,settled?"settled":(signed?"unknown":"failed"),settlement?.transaction??null,response.status,settled?null:`paid request returned ${response.status}`);return{payment_id:paymentId,status:settled?"settled":"unknown",purpose,response_status:response.status,transaction:settlement?.transaction??null,network:settlement?.network??BASE_NETWORK,result:body};
    }catch(e){await this.store.finishPayment(paymentId,signed?"unknown":"failed",null,null,errorMessage(e));throw e;}
  }

  private async account(userId:string){const name=`x402-${createHash("sha256").update(userId).digest("hex").slice(0,24)}`;const existing=await this.store.getWallet(userId);const account=await this.cdp.evm.getOrCreateAccount({name:existing?.accountName??name});if(!existing?.address)await this.store.saveWallet(userId,name,account.address);return account;}
  private async resolveRef(ref:string){const url=(await this.tokens.verifyServiceRef(ref));assertSafeResourceUrl(url);const found=await searchX402Resources({urlSubstring:url,network:BASE_NETWORK,asset:BASE_USDC,scheme:"exact"});if(!found.resources.some(r=>r.resource===url&&(r.accepts??[]).some(isAllowedLike)))throw new Error("resource is no longer an eligible CDP Bazaar listing");return url;}
  private async preflight(url:string,spec:RequestSpec){const response=await safeFetch(url,requestInit(spec,this.config.PAYMENT_TIMEOUT_MS));if(response.status!==402)throw new Error(`resource did not return 402 (received ${response.status})`);const header=response.headers.get("payment-required")??response.headers.get("x-payment-required");if(!header)throw new Error("resource returned 402 without PAYMENT-REQUIRED");return decodePaymentRequiredHeader(header);}
}

function requestInit(spec:RequestSpec,timeout:number):RequestInit{const init:RequestInit={method:spec.method,signal:AbortSignal.timeout(timeout)};if(spec.method==="POST"&&spec.body!==undefined){init.headers={"content-type":"application/json"};init.body=JSON.stringify(spec.body);}return init;}
function isAllowed(r:PaymentRequirements){return r.scheme==="exact"&&r.network===BASE_NETWORK&&r.asset.toLowerCase()===BASE_USDC&&/^0x[0-9a-fA-F]{40}$/.test(r.payTo)&&/^\d+$/.test(r.amount)&&BigInt(r.amount)>0n;}
function selectRequirement(challenge:PaymentRequired,config:Config){if(challenge.x402Version!==2)throw new Error("only x402 v2 is supported");const valid=challenge.accepts.filter(isAllowed).filter(r=>BigInt(r.amount)<=BigInt(config.MAX_PAYMENT_USDC_ATOMIC));if(!valid.length)throw new Error("no eligible Base USDC exact payment under the per-payment limit");return [...valid].sort((a,b)=>BigInt(a.amount)<BigInt(b.amount)?-1:1)[0]!;}
function publicRequirement(r:PaymentRequirements){return{scheme:r.scheme,network:r.network,asset:r.asset,amount_atomic:r.amount,amount_usdc:atomicUsd(r.amount),pay_to:r.payTo,max_timeout_seconds:r.maxTimeoutSeconds};}
type RequirementLike={scheme:string;network:string;asset:string;amount:string;payTo:string;maxTimeoutSeconds:number;extra?:Record<string,unknown>};
function isAllowedLike(value:unknown):value is RequirementLike{if(!value||typeof value!=="object")return false;const r=value as Record<string,unknown>;return r.scheme==="exact"&&r.network===BASE_NETWORK&&typeof r.asset==="string"&&r.asset.toLowerCase()===BASE_USDC&&typeof r.payTo==="string"&&/^0x[0-9a-fA-F]{40}$/.test(r.payTo)&&typeof r.amount==="string"&&/^\d+$/.test(r.amount)&&BigInt(r.amount)>0n&&typeof r.maxTimeoutSeconds==="number";}
function publicRequirementLike(r:RequirementLike){return{scheme:r.scheme,network:r.network,asset:r.asset,amount_atomic:r.amount,amount_usdc:atomicUsd(r.amount),pay_to:r.payTo,max_timeout_seconds:r.maxTimeoutSeconds};}
function atomicUsd(value:string){const n=value.padStart(7,"0");return`${n.slice(0,-6)}.${n.slice(-6)}`.replace(/\.0+$/,"").replace(/(\.\d*?)0+$/,"$1");}
function stable(value:unknown):string{if(Array.isArray(value))return`[${value.map(stable).join(",")}]`;if(value&&typeof value==="object")return`{${Object.entries(value as Record<string,unknown>).sort(([a],[b])=>a.localeCompare(b)).map(([k,v])=>`${JSON.stringify(k)}:${stable(v)}`).join(",")}}`;return JSON.stringify(value);}
export function requirementFingerprint(p:PaymentRequired,r:PaymentRequirements,url:string,spec:RequestSpec){return createHash("sha256").update(stable({v:p.x402Version,resource:p.resource.url,url,method:spec.method,body:spec.body??null,scheme:r.scheme,network:r.network,asset:r.asset.toLowerCase(),amount:r.amount,payTo:r.payTo.toLowerCase(),timeout:r.maxTimeoutSeconds,extra:r.extra})).digest("base64url");}
function decodeSettlement(response:Response):{success:boolean;transaction?:string;network?:string}|null{const h=response.headers.get("payment-response")??response.headers.get("x-payment-response");if(!h)return null;try{return JSON.parse(Buffer.from(h,"base64").toString("utf8"));}catch{return null;}}
function errorMessage(e:unknown){return e instanceof Error?e.message:String(e);}
