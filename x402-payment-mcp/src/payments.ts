import { createHash } from "node:crypto";
import { CdpClient, searchX402Resources } from "@coinbase/cdp-sdk";
import { getDefaultEvmRpcUrls } from "@coinbase/cdp-sdk/x402";
import { x402Client, x402HTTPClient } from "@x402/core/client";
import { decodePaymentRequiredHeader } from "@x402/core/http";
import type { PaymentRequired, PaymentRequirements } from "@x402/core/types";
import { AuthCaptureEvmScheme } from "@x402/evm/auth-capture/client";
import { BatchSettlementEvmScheme, type BatchSettlementClientContext, type ClientChannelStorage } from "@x402/evm/batch-settlement/client";
import { registerExactEvmScheme } from "@x402/evm/exact/client";
import { UptoEvmScheme } from "@x402/evm/upto/client";
import { toClientEvmSigner } from "@x402/evm";
import { createSIWxClientExtension } from "@x402/extensions/sign-in-with-x";
import { createPublicClient, http } from "viem";
import { base } from "viem/chains";
import { BASE_NETWORK, BASE_USDC, type Config } from "./config.js";
import { assertSafeResourceUrl, limitedBody, safeFetch, safeFetchManual } from "./network.js";
import { TokenService } from "./security.js";
import { Store } from "./store.js";

export type QueryValue=string|number|boolean;
export const HTTP_METHODS=["GET","POST","PUT","PATCH","DELETE"] as const;
export type HttpMethod=typeof HTTP_METHODS[number];
export type RequestSpec={method:HttpMethod;query?:Record<string,QueryValue>;headers?:Record<string,string>;body?:unknown;textBody?:string};
// method is omitted when the caller wants it detected from the Bazaar listing or the provider's 405.
export type PreviewSpec=Omit<RequestSpec,"method">&{method?:HttpMethod};
export type DiscoveryProvider="bazaar"|"agentic_market";
const AGENTIC_MARKET_API="https://api.agentic.market/v1";
const DISCOVERY_TIMEOUT_MS=15_000;
export type ResourceTarget={url?:string;serviceRef?:string};
const UNLISTED_WARNING="This URL is not a CDP Bazaar listing. Pay only if the user supplied or confirmed this exact URL, recipient and amount.";
export type PaymentScheme="exact"|"upto"|"batch-settlement"|"auth-capture";

export class PaymentService{
  private readonly cdp:CdpClient;
  private readonly baseRpcUrl:Promise<string|undefined>;
  constructor(private config:Config,private store:Store,private tokens:TokenService){this.cdp=new CdpClient({apiKeyId:config.CDP_API_KEY_ID,apiKeySecret:config.CDP_API_KEY_SECRET,walletSecret:config.CDP_WALLET_SECRET});this.baseRpcUrl=getDefaultEvmRpcUrls().then(urls=>urls[BASE_NETWORK]?.rpcUrl);}

  async search(query:string,limit:number,provider:DiscoveryProvider="bazaar"){if(provider==="agentic_market")return this.searchAgenticMarket(query,limit);const found=await searchX402Resources({query:query.slice(0,400),network:BASE_NETWORK,asset:BASE_USDC,...(this.config.SPEND_LIMITS_ENABLED?{maxUsdPrice:atomicUsd(this.config.MAX_PAYMENT_USDC_ATOMIC)}:{})});const eligible=found.resources.map(r=>({resource:r,accepts:(r.accepts??[]).filter(isAllowedLike) as unknown as RequirementLike[]})).filter(r=>r.accepts.length>0).slice(0,limit);const resources=eligible.map(({resource:r,accepts})=>({url:r.resource,service_name:r.serviceName,description:r.description,type:r.type,accepts:accepts.map(publicRequirementLike),quality:r.quality,tags:r.tags,...inputHint(r.extensions)}));return{provider:"bazaar",resources,partial_results:found.partialResults,search_method:found.searchMethod};}

  private async searchAgenticMarket(query:string,limit:number){const response=await safeFetch(`${AGENTIC_MARKET_API}/services/search?q=${encodeURIComponent(query.slice(0,400))}`,{headers:{accept:"application/json"},signal:AbortSignal.timeout(DISCOVERY_TIMEOUT_MS)});const body=await limitedBody(response);if(!response.ok)throw new Error(`Agentic Market search failed (HTTP ${response.status})`);return{provider:"agentic_market",resources:agenticMarketResources(body,limit)};}

  async walletStatus(userId:string){const account=await this.account(userId);const scoped=await account.useNetwork("base");const result=await scoped.listTokenBalances({pageSize:100});const usdc=result.balances.find(b=>b.token.contractAddress.toLowerCase()===BASE_USDC);return{network:BASE_NETWORK,address:account.address,usdc_atomic:usdc?.amount.amount.toString()??"0",usdc_decimals:usdc?.amount.decimals??6,spend_limits_enabled:this.config.SPEND_LIMITS_ENABLED,per_payment_limit_atomic:this.config.SPEND_LIMITS_ENABLED?this.config.MAX_PAYMENT_USDC_ATOMIC:null,daily_limit_atomic:this.config.SPEND_LIMITS_ENABLED?this.config.MAX_DAILY_USDC_ATOMIC:null};}

  async preview(userId:string,target:ResourceTarget,input:PreviewSpec,scheme:"auto"|PaymentScheme="auto"){if(hasBody(input)&&input.textBody!==undefined)throw new Error("provide either body or text_body, not both");const headers=normalizeRequestHeaders(input.headers);const request:PreviewSpec={...input,...(headers?{headers}:{})};const baseUrl=await this.resolveTarget(target);const requested=buildResourceUrl(baseUrl,request.query);const listing=await this.bazaarListing(baseUrl);const listed=listing.listed;const {method,url,header,challenge}=await preflight(safeFetchManual,requested,request,request.method?[request.method]:methodCandidates(listing.method,hasBody(request)),Math.min(this.config.PAYMENT_TIMEOUT_MS,PREFLIGHT_TIMEOUT_MS));const spec:RequestSpec={...request,method};const selected=selectRequirement(challenge,this.config,scheme);const fingerprint=requirementFingerprint(challenge,selected,url,spec);const saved=await this.store.createPreview({userId,method:spec.method,url,headers:spec.headers??null,body:spec.body??null,textBody:spec.textBody??null,paymentRequired:header,fingerprint,scheme:selected.scheme,amount:selected.amount,payTo:selected.payTo},this.config.PREVIEW_TTL_SECONDS);return{preview_id:saved.id,expires_at:saved.expiresAt.toISOString(),resource:{url,...(url!==requested?{redirected_from:requested}:{}),description:challenge.resource.description,service_name:challenge.resource.serviceName,bazaar_listed:listed,...(listed===true?{}:{warning:UNLISTED_WARNING})},payment:publicRequirement(selected),request:{method:spec.method,query:spec.query??{},header_names:Object.keys(spec.headers??{}),has_body:hasBody(spec)||spec.textBody!==undefined}};}

  async pay(userId:string,previewId:string,purpose:string){return this.store.withPaymentLock(userId,()=>this.payLocked(userId,previewId,purpose));}

  private async payLocked(userId:string,previewId:string,purpose:string){
    const dailyLimit=this.config.SPEND_LIMITS_ENABLED?BigInt(this.config.MAX_DAILY_USDC_ATOMIC):null;const {paymentId,preview}=await this.store.reservePayment(userId,previewId,dailyLimit,purpose);const stored=storedRequest(preview);let signed=false;
    try{
      if(!preview.paymentRequired)throw new Error("preview was created before a server upgrade; call x402_preview again");
      const paymentRequired=decodePaymentRequiredHeader(preview.paymentRequired);
      const client=await this.client(userId,preview);
      client.onBeforePaymentCreation(async({paymentRequired:terms,selectedRequirements})=>{if(requirementFingerprint(terms,selectedRequirements,preview.url,stored)!==preview.fingerprint)return{abort:true,reason:"stored payment terms do not match the preview"};});
      client.onAfterPaymentCreation(async()=>{signed=true;});
      const {response,paid}=await payStoredChallenge({client,fetchImpl:safeFetch,url:preview.url,request:stored,paymentRequired,timeout:this.config.PAYMENT_TIMEOUT_MS});
      const body=await readResult(response);
      if(!paid){await this.store.finishPayment(paymentId,"failed",null,response.status,NOT_CHARGED_NOTE);return{payment_id:paymentId,status:"not_charged",note:NOT_CHARGED_NOTE,scheme:preview.scheme,purpose,authorized_amount_atomic:preview.amount,settled_amount_atomic:null,response_status:response.status,transaction:null,network:BASE_NETWORK,result:body};}const settlement=decodeSettlement(response);const settled=response.ok&&settlement?.success===true;const reason=settled?null:unsettledReason(response,body);
      await this.store.finishPayment(paymentId,settled?"settled":"unknown",settlement?.transaction??null,response.status,reason,settlement?.amount??null);
      return{payment_id:paymentId,status:settled?"settled":"unknown",...(reason?{failure_reason:reason,next_step:UNKNOWN_NEXT_STEP}:{}),scheme:preview.scheme,purpose,authorized_amount_atomic:preview.amount,settled_amount_atomic:settlement?.amount??null,response_status:response.status,transaction:settlement?.transaction??null,network:settlement?.network??BASE_NETWORK,result:body};
    }catch(e){
      await this.store.finishPayment(paymentId,signed?"unknown":"failed",null,null,errorMessage(e));
      // Before signing nothing can be charged; after signing the provider holds a valid authorization, so the outcome is unknown rather than failed.
      throw new Error(signed?`payment was signed but the paid request did not complete (${errorMessage(e)}). Settlement is unknown. ${UNKNOWN_NEXT_STEP}`:`payment was not made: ${errorMessage(e)}. Nothing was signed or charged; call x402_preview again to retry`);
    }
    // Caller-supplied headers may be sensitive; drop them as soon as the single use is over.
    finally{await this.store.scrubPreview(previewId).catch(error=>console.error("preview scrub failed",errorMessage(error)));}
  }

  private async client(userId:string,preview:import("./store.js").Preview){
    const account=await this.account(userId);const rpcUrl=await this.baseRpcUrl;const publicClient=createPublicClient({chain:base,transport:http(rpcUrl)});const signer=toClientEvmSigner(account,publicClient);const schemeOptions=rpcUrl?{rpcUrl}:undefined;
    const client=new x402Client((_version,requirements)=>selectPreviewRequirement(requirements,preview));client.setSpendControls(this.config.SPEND_LIMITS_ENABLED?{maxAmountPerPayment:`$${atomicUsd(this.config.MAX_PAYMENT_USDC_ATOMIC)}`,allowedAssets:[]}:false);
    registerExactEvmScheme(client,{signer,networks:[BASE_NETWORK],...(schemeOptions?{schemeOptions}:{})});client.register(BASE_NETWORK,new UptoEvmScheme(signer,schemeOptions));client.register(BASE_NETWORK,new BatchSettlementEvmScheme(signer,{storage:new PostgresBatchChannelStorage(this.store,userId),...(rpcUrl?{rpcUrl}:{})}));client.register(BASE_NETWORK,new AuthCaptureEvmScheme(signer));client.registerPolicy((_v,reqs)=>reqs.filter(isAllowed));
    client.registerExtension(createSIWxClientExtension({signers:[{address:account.address,signMessage:({message}:{message:string})=>account.signMessage({message})}]}));
    return client;
  }

  // One CDP EVM account per user, shared by Base x402 payments and Arc transfers.
  async account(userId:string){const name=`x402-${createHash("sha256").update(userId).digest("hex").slice(0,24)}`;const existing=await this.store.getWallet(userId);const account=await this.cdp.evm.getOrCreateAccount({name:existing?.accountName??name});if(!existing?.address)await this.store.saveWallet(userId,name,account.address);return account;}
  // Any public HTTPS x402 endpoint can be paid, as in the local wallet. service_ref is still accepted from clients holding an older search result.
  private async resolveTarget(target:ResourceTarget){const raw=target.url??(target.serviceRef?await this.tokens.verifyServiceRef(target.serviceRef):undefined);if(!raw)throw new Error("provide the url of the x402 resource");assertNoPathPlaceholders(raw);return assertSafeResourceUrl(raw).toString();}
  // Informational only: a Bazaar outage must not block a payment the user asked for.
  private async bazaarListing(url:string):Promise<{listed:boolean|null;method?:HttpMethod}>{try{const found=await searchX402Resources({urlSubstring:listingKey(url),network:BASE_NETWORK,asset:BASE_USDC});const listing=findListing(found.resources,url);const method=listing?hintedMethod(listing.extensions):undefined;return{listed:Boolean(listing),...(method?{method}:{})};}catch{return{listed:null};}}
}

const NOT_CHARGED_NOTE="not charged: the provider accepted the wallet sign-in and returned the resource without a payment";
const UNKNOWN_NEXT_STEP="Do not pay again blindly: call wallet_status to see whether the balance changed before previewing a new payment.";
// Signs the challenge captured at preview time and sends one paid request, as the local wallet does. The amount and recipient the user approved are the only terms that can be signed; a provider that changed its price answers 402 again and nothing settles.
// Every request gets its own timeout, so a slow on-chain settlement is not cut short by time already spent signing.
export async function payStoredChallenge(o:{client:x402Client;fetchImpl:typeof globalThis.fetch;url:string;request:RequestSpec;paymentRequired:PaymentRequired;timeout:number}):Promise<{response:Response;paid:boolean}>{
  const httpClient=new x402HTTPClient(o.client);
  const send=(extra:Record<string,string>)=>{const init=requestInit(o.request,o.timeout);return o.fetchImpl(o.url,{...init,headers:{...(init.headers as Record<string,string>|undefined),...extra}});};
  // Sign-In-With-X: a provider that declares it may grant access to a wallet that already paid. Best effort, as in the local wallet: a challenge that cannot be signed must not block the payment.
  const signIn=await httpClient.handlePaymentRequired(o.paymentRequired,o.url).catch(()=>null)??{};
  if(Object.keys(signIn).length){const granted=await send(signIn);if(granted.status!==402)return{response:granted,paid:false};void granted.body?.cancel().catch(()=>{});}
  const attempt=async()=>{const payload=await o.client.createPaymentPayload(o.paymentRequired);const response=await send({...signIn,...httpClient.encodePaymentSignatureHeader(payload)});const result=await httpClient.processPaymentResult(payload,name=>response.headers.get(name),response.status);return{response,recovered:result.recovered};};
  const first=await attempt();if(!first.recovered)return{response:first.response,paid:true};
  // A scheme hook (batch-settlement channel resync) repaired local state and asked for one retry with a fresh payload.
  void first.response.body?.cancel().catch(()=>{});return{response:(await attempt()).response,paid:true};
}
// The settlement arrives in a header, so a body that is too large or breaks mid-stream must not turn a settled payment into an unknown one.
export async function readResult(response:Response):Promise<unknown>{try{return await limitedBody(response);}catch(e){return{result_unavailable:`the response body could not be read: ${errorMessage(e)}`};}}
// The provider's own explanation for refusing a signed payment, when it gives one.
export function unsettledReason(response:Response,body:unknown){
  let detail="";const header=response.headers.get("payment-required")??response.headers.get("x-payment-required");
  if(header){try{const error=(decodePaymentRequiredHeader(header) as {error?:unknown}).error;if(typeof error==="string")detail=error;}catch{}}
  if(!detail&&body!==null&&body!==undefined){try{detail=typeof body==="string"?body:JSON.stringify(body);}catch{detail=String(body);}}
  detail=detail.replace(/\s+/g," ").trim().slice(0,500);
  const what=response.status===402?"provider refused the signed payment and still asks for payment":response.ok?"provider answered without reporting a settlement":`paid request returned HTTP ${response.status}`;
  return`${what}${detail?`; provider response (untrusted): ${detail}`:""}`;
}
// Tries each candidate method in order. Providers answer the wrong verb with 405, 404, 401 or a 402 that carries no challenge, so any client error moves on to the next candidate; a wrong default then costs one extra unpaid request instead of a failed preview. The first failure is the one reported, since it belongs to the preferred method.
// Redirects are followed here, hop by hop through the SSRF guard, and the preview is bound to the final url so the paid request never has to follow one.
export async function preflight(fetchImpl:typeof globalThis.fetch,startUrl:string,request:PreviewSpec,methods:HttpMethod[],timeout:number){
  let failure:Error|undefined;
  for(const method of methods){
    let url=startUrl;let response=await reach(fetchImpl,url,{...request,method},timeout);
    for(let hop=0;REDIRECT_STATUSES.has(response.status);hop++){if(hop>=MAX_REDIRECTS)throw new Error(`resource redirected more than ${MAX_REDIRECTS} times`);url=redirectTarget(url,response,method,Boolean(request.headers));void response.body?.cancel().catch(()=>{});response=await reach(fetchImpl,url,{...request,method},timeout);}
    const header=response.status===402?response.headers.get("payment-required")??response.headers.get("x-payment-required"):null;
    if(header)return{method,url,header,challenge:decodePaymentRequiredHeader(header)};
    const body=await limitedBody(response,64_000);failure??=new Error(response.status===402?`resource returned 402 without PAYMENT-REQUIRED (${method})`:preflightFailureMessage(response.status,body,method));
    if(response.status<400||response.status>=500||response.status===429)break;
  }
  throw failure??new Error("no HTTP method to try");
}
// An unpaid probe is safe to repeat, so one transient connection error is retried; the paid request never is. A failure names the network cause instead of undici's bare "fetch failed".
async function reach(fetchImpl:typeof globalThis.fetch,url:string,spec:RequestSpec,timeout:number){
  for(let attempt=0;;attempt++){try{return await fetchImpl(url,requestInit(spec,timeout));}catch(e){const cause=(e as {cause?:{code?:string;message?:string}}).cause;const timedOut=e instanceof Error&&(e.name==="TimeoutError"||e.name==="AbortError");if(attempt===0&&!timedOut&&cause)continue;throw new Error(`could not reach the resource before payment: ${timedOut?`no response within ${timeout} ms`:[cause?.code,cause?.message??errorMessage(e)].filter(Boolean).join(" ")}`);}}
}
// An unpaid probe settles nothing on-chain, and a preview can need several of them (method fallback, redirects, one retry), so each gets less time than a paid request.
const PREFLIGHT_TIMEOUT_MS=15_000;
const MAX_REDIRECTS=5;
const REDIRECT_STATUSES=new Set([301,302,303,307,308]);
function redirectTarget(from:string,response:Response,method:HttpMethod,hasHeaders:boolean){
  const location=response.headers.get("location");if(!location)throw new Error(`resource returned HTTP ${response.status} without a location`);
  const next=assertSafeResourceUrl(new URL(location,from).toString());
  // 301/302/303 turn a non-GET into a GET in every HTTP client; following them would pay for a different request than the one previewed.
  if(method!=="GET"&&response.status!==307&&response.status!==308)throw new Error(`resource redirects ${method} with HTTP ${response.status}, which would change the method; preview ${next.toString()} directly`);
  if(hasHeaders&&next.origin!==new URL(from).origin)throw new Error(`resource redirects to another host; preview ${next.toString()} directly so headers are not sent to a host you did not name`);
  return next.toString();
}
// A preview stores "no body" as SQL/JSON null, so null and undefined must build the same request at preview and at pay time.
export function requestInit(spec:RequestSpec,timeout:number):RequestInit{
  const headers:Record<string,string>={...(spec.headers??{})};const init:RequestInit={method:spec.method,signal:AbortSignal.timeout(timeout)};
  if(spec.method!=="GET"&&hasBody(spec)){if(!("content-type" in headers))headers["content-type"]="application/json";init.body=JSON.stringify(spec.body);}
  else if(spec.method!=="GET"&&typeof spec.textBody==="string")init.body=spec.textBody;
  if(Object.keys(headers).length)init.headers=headers;return init;
}
function storedRequest(preview:import("./store.js").Preview):RequestSpec{return{method:preview.method as HttpMethod,...(preview.headers?{headers:preview.headers}:{}),body:preview.body,...(typeof preview.textBody==="string"?{textBody:preview.textBody}:{})};}
// Hop-by-hop and payment headers belong to this server; everything else is the caller's to set, as in the local wallet.
const BLOCKED_HEADERS=new Set(["host","content-length","transfer-encoding","connection","upgrade","te","trailer","keep-alive","expect","payment-signature","x-payment","access-control-expose-headers"]);
export function normalizeRequestHeaders(raw:Record<string,string>|undefined):Record<string,string>|undefined{
  const entries=Object.entries(raw??{});if(!entries.length)return undefined;if(entries.length>20)throw new Error("headers supports at most 20 entries");const out:Record<string,string>={};
  for(const [key,value] of entries){const name=key.trim().toLowerCase();if(!/^[a-z0-9!#$%&'*+.^_`|~-]{1,100}$/.test(name))throw new Error(`invalid header name: ${key.slice(0,40)}`);if(BLOCKED_HEADERS.has(name)||name.startsWith("proxy-"))throw new Error(`header ${name} cannot be set by the caller`);if(typeof value!=="string"||value.length>2000||/[\r\n\0]/.test(value))throw new Error(`invalid value for header ${name}`);out[name]=value;}
  return out;
}
export function buildResourceUrl(raw:string,query?:Record<string,QueryValue>){const url=assertSafeResourceUrl(raw);const entries=Object.entries(query??{});if(entries.length>32)throw new Error("query supports at most 32 parameters");for(const [key,value] of entries){const name=key.trim();if(!name)throw new Error("query parameter names must not be empty");if(name.length>100)throw new Error("query parameter names must be at most 100 characters");if(typeof value==="number"&&!Number.isFinite(value))throw new Error(`query parameter ${name} must be finite`);const text=String(value);if(text.length>500)throw new Error(`query parameter ${name} must be at most 500 characters`);url.searchParams.set(name,text);}const result=url.toString();if(result.length>4096)throw new Error("resource URL with query parameters is too long");return result;}
// Agentic Market groups endpoints under a service and quotes prices in whole USDC. Only endpoints this wallet can pay (USDC on Base) are returned, one row per endpoint, in the same shape as Bazaar results. Listing data is the provider's own and is not verified here; x402_preview reads the real terms.
export function agenticMarketResources(payload:unknown,limit:number){
  const services=isRecord(payload)&&Array.isArray(payload.services)?payload.services:[];const out:Record<string,unknown>[]=[];
  for(const service of services){if(!isRecord(service)||!Array.isArray(service.endpoints))continue;
    for(const endpoint of service.endpoints){if(out.length>=limit)return out;if(!isRecord(endpoint)||typeof endpoint.url!=="string")continue;const pricing=isRecord(endpoint.pricing)?endpoint.pricing:{};const network=String(pricing.network??"").toLowerCase();
      if(String(pricing.currency??"").toUpperCase()!=="USDC"||(network!==BASE_NETWORK&&network!=="base"))continue;try{assertSafeResourceUrl(endpoint.url);}catch{continue;}
      const method=typeof endpoint.method==="string"?endpoint.method.toUpperCase():undefined;
      out.push({url:endpoint.url,service_name:textField(endpoint.serviceName)??textField(service.name),description:textField(endpoint.description)??textField(service.description),...(method&&(HTTP_METHODS as readonly string[]).includes(method)?{method}:{}),price_usdc:textField(pricing.amount)??null,scheme:textField(pricing.scheme)??"exact",network:BASE_NETWORK,listing_trust:"untrusted marketplace metadata"});}}
  return out;
}
function textField(value:unknown){return typeof value==="string"&&value.trim()?value.trim().slice(0,500):undefined;}
// Bazaar lists templated resources such as /wallet/:address/portfolio; requesting them verbatim only returns 404.
export function assertNoPathPlaceholders(raw:string){const path=raw.split(/[?#]/)[0]!;const found=path.match(/\{[^}/]+\}|%7B[^/]+?%7D|\/:[A-Za-z_]\w*/i);if(found)throw new Error(`url still contains the path placeholder ${found[0].replace(/^\//,"")}; replace it with a real value`);}
function hasBody(spec:{body?:unknown}){return spec.body!==undefined&&spec.body!==null;}
// 40% of Bazaar listings are POST-only; a blind GET default made those previews fail with 405.
export function methodCandidates(hinted:HttpMethod|undefined,withBody:boolean):HttpMethod[]{const first=hinted??(withBody?"POST":"GET");return first==="GET"?["GET","POST"]:first==="POST"?["POST","GET"]:[first];}
export function hintedMethod(extensions:unknown):HttpMethod|undefined{const method=(extensions as {bazaar?:{info?:{input?:{method?:unknown}}}}|undefined)?.bazaar?.info?.input?.method;const upper=typeof method==="string"?method.toUpperCase():"";return (HTTP_METHODS as readonly string[]).includes(upper)?upper as HttpMethod:undefined;}
function listingKey(raw:string){const url=new URL(raw);return`${url.host}${url.pathname}`;}
export function findListing<T extends {resource:string;accepts?:unknown[]}>(resources:readonly T[],raw:string):T|undefined{const key=listingKey(raw);return resources.find(r=>{try{return listingKey(r.resource)===key&&(r.accepts??[]).some(isAllowedLike);}catch{return false;}});}
// Bazaar "info.input" tells callers which query parameters/body a resource expects; provider-supplied, so bounded and labelled untrusted.
export function inputHint(extensions:unknown){const info=(extensions as {bazaar?:{info?:{input?:unknown}}}|undefined)?.bazaar?.info?.input;if(info===undefined||info===null)return{};let text:string;try{text=JSON.stringify(info);}catch{return{};}if(!text||text==="{}")return{};return text.length<=2000?{input:info,input_trust:"untrusted provider metadata"}:{input_truncated:text.slice(0,2000),input_trust:"untrusted provider metadata"};}
export function preflightFailureMessage(status:number,body:unknown,method?:HttpMethod){let detail="";if(typeof body==="string")detail=body;else if(body!==null&&body!==undefined){try{detail=JSON.stringify(body);}catch{detail=String(body);}}detail=detail.replace(/\s+/g," ").trim().slice(0,2000);return `resource request failed before payment (${method?`${method}, `:""}HTTP ${status})${detail?`; provider response (untrusted): ${detail}`:""}`;}
function isAllowed(r:PaymentRequirements):r is PaymentRequirements&{scheme:PaymentScheme}{return isSupportedScheme(r.scheme)&&r.network===BASE_NETWORK&&r.asset.toLowerCase()===BASE_USDC&&isAddress(r.payTo)&&/^\d+$/.test(r.amount)&&BigInt(r.amount)>0n&&validSchemeExtra(r.scheme,r.extra);}
export function selectRequirement(challenge:PaymentRequired,config:Config,requested:"auto"|PaymentScheme="auto"){if(challenge.x402Version!==2)throw new Error("only x402 v2 is supported");const eligible=challenge.accepts.filter(isAllowed).filter(r=>requested==="auto"||r.scheme===requested);const valid=config.SPEND_LIMITS_ENABLED?eligible.filter(r=>BigInt(r.amount)<=BigInt(config.MAX_PAYMENT_USDC_ATOMIC)):eligible;if(!valid.length)throw new Error(config.SPEND_LIMITS_ENABLED?"no eligible Base USDC payment under the per-payment limit":"no eligible Base USDC payment for the requested scheme");const priority:Record<PaymentScheme,number>={exact:0,upto:1,"batch-settlement":2,"auth-capture":3};return [...valid].sort((a,b)=>priority[a.scheme]-priority[b.scheme]||(BigInt(a.amount)<BigInt(b.amount)?-1:BigInt(a.amount)>BigInt(b.amount)?1:0))[0]!;}
function selectPreviewRequirement(requirements:PaymentRequirements[],preview:import("./store.js").Preview){const selected=requirements.find(r=>r.scheme===preview.scheme&&r.network===BASE_NETWORK&&r.asset.toLowerCase()===BASE_USDC&&r.amount===preview.amount&&r.payTo.toLowerCase()===preview.payTo.toLowerCase());if(!selected)throw new Error("previewed payment option is no longer offered");return selected;}
function publicRequirement(r:PaymentRequirements){if(!isSupportedScheme(r.scheme))throw new Error("unsupported payment scheme");return{scheme:r.scheme,network:r.network,asset:r.asset,amount_atomic:r.amount,amount_usdc:atomicUsd(r.amount),amount_semantics:r.scheme==="exact"?"exact":"maximum authorized",pay_to:r.payTo,max_timeout_seconds:r.maxTimeoutSeconds,...publicSchemeDetails(r.scheme,r.amount,r.extra)};}
type RequirementLike={scheme:string;network:string;asset:string;amount:string;payTo:string;maxTimeoutSeconds:number;extra?:Record<string,unknown>};
function isAllowedLike(value:unknown):value is RequirementLike{if(!value||typeof value!=="object")return false;const r=value as Record<string,unknown>;return isSupportedScheme(r.scheme)&&r.network===BASE_NETWORK&&typeof r.asset==="string"&&r.asset.toLowerCase()===BASE_USDC&&typeof r.payTo==="string"&&isAddress(r.payTo)&&typeof r.amount==="string"&&/^\d+$/.test(r.amount)&&BigInt(r.amount)>0n&&typeof r.maxTimeoutSeconds==="number"&&Number.isSafeInteger(r.maxTimeoutSeconds)&&r.maxTimeoutSeconds>0&&validSchemeExtra(r.scheme,isRecord(r.extra)?r.extra:{});}
function publicRequirementLike(r:RequirementLike){return{scheme:r.scheme,network:r.network,asset:r.asset,amount_atomic:r.amount,amount_usdc:atomicUsd(r.amount),amount_semantics:r.scheme==="exact"?"exact":"maximum authorized",pay_to:r.payTo,max_timeout_seconds:r.maxTimeoutSeconds,...publicSchemeDetails(r.scheme as PaymentScheme,r.amount,r.extra??{})};}
function publicSchemeDetails(scheme:PaymentScheme,amount:string,extra:Record<string,unknown>){return{...(scheme==="batch-settlement"?{channel_funding:{initial_deposit_atomic:(BigInt(amount)*5n).toString(),initial_deposit_usdc:atomicUsd((BigInt(amount)*5n).toString()),note:"SDK default; reusable channel balance, not the current charge"}}:{}),...(typeof extra.paymentFlow==="string"?{payment_flow:extra.paymentFlow}:{}),...(typeof extra.assetTransferMethod==="string"?{asset_transfer_method:extra.assetTransferMethod}:{}),...(typeof extra.captureDeadline==="number"?{capture_deadline:extra.captureDeadline}:{}),...(typeof extra.refundDeadline==="number"?{refund_deadline:extra.refundDeadline}:{}),...(typeof extra.minFeeBps==="number"?{min_fee_bps:extra.minFeeBps}:{}),...(typeof extra.maxFeeBps==="number"?{max_fee_bps:extra.maxFeeBps}:{}),...(typeof extra.withdrawDelay==="number"?{withdraw_delay_seconds:extra.withdrawDelay}:{})};}
function isSupportedScheme(value:unknown):value is PaymentScheme{return value==="exact"||value==="upto"||value==="batch-settlement"||value==="auth-capture";}
function isRecord(value:unknown):value is Record<string,unknown>{return !!value&&typeof value==="object"&&!Array.isArray(value);}
function isAddress(value:unknown):value is string{return typeof value==="string"&&/^0x[0-9a-fA-F]{40}$/.test(value);}
function isNonZeroAddress(value:unknown){return isAddress(value)&&!/^0x0{40}$/i.test(value);}
function validTransferMethod(value:unknown){return value===undefined||value==="eip3009"||value==="permit2";}
function validSchemeExtra(scheme:PaymentScheme,extra:Record<string,unknown>){
  if(scheme==="exact")return validTransferMethod(extra.assetTransferMethod);
  if(scheme==="upto")return isNonZeroAddress(extra.facilitatorAddress)&&(extra.assetTransferMethod===undefined||extra.assetTransferMethod==="permit2");
  if(scheme==="batch-settlement"){const delay=extra.withdrawDelay;return isNonZeroAddress(extra.receiverAuthorizer)&&validTransferMethod(extra.assetTransferMethod)&&(delay===undefined||(typeof delay==="number"&&Number.isSafeInteger(delay)&&delay>=900&&delay<=2_592_000));}
  const capture=extra.captureDeadline,refund=extra.refundDeadline,minFee=extra.minFeeBps,maxFee=extra.maxFeeBps;
  return typeof extra.name==="string"&&extra.name.length>0&&typeof extra.version==="string"&&extra.version.length>0&&isNonZeroAddress(extra.captureAuthorizer)&&isNonZeroAddress(extra.feeRecipient)&&validTransferMethod(extra.assetTransferMethod)&&typeof capture==="number"&&Number.isSafeInteger(capture)&&capture>0&&typeof refund==="number"&&Number.isSafeInteger(refund)&&refund>=capture&&typeof minFee==="number"&&Number.isInteger(minFee)&&minFee>=0&&minFee<=10_000&&typeof maxFee==="number"&&Number.isInteger(maxFee)&&maxFee>=minFee&&maxFee<=10_000;
}
function atomicUsd(value:string){const n=value.padStart(7,"0");return`${n.slice(0,-6)}.${n.slice(-6)}`.replace(/\.0+$/,"").replace(/(\.\d*?)0+$/,"$1");}
function stable(value:unknown):string{if(Array.isArray(value))return`[${value.map(stable).join(",")}]`;if(value&&typeof value==="object")return`{${Object.entries(value as Record<string,unknown>).sort(([a],[b])=>a.localeCompare(b)).map(([k,v])=>`${JSON.stringify(k)}:${stable(v)}`).join(",")}}`;return JSON.stringify(value);}
export function requirementFingerprint(p:PaymentRequired,r:PaymentRequirements,url:string,spec:RequestSpec){return createHash("sha256").update(stable({v:p.x402Version,resource:p.resource.url,url,method:spec.method,body:spec.body??null,textBody:spec.textBody??null,scheme:r.scheme,network:r.network,asset:r.asset.toLowerCase(),amount:r.amount,payTo:r.payTo.toLowerCase(),timeout:r.maxTimeoutSeconds,extra:r.extra})).digest("base64url");}
function decodeSettlement(response:Response):{success:boolean;transaction?:string;network?:string;amount?:string}|null{const h=response.headers.get("payment-response")??response.headers.get("x-payment-response");if(!h)return null;try{const value=JSON.parse(Buffer.from(h,"base64").toString("utf8")) as Record<string,unknown>;const extra=value.extra&&typeof value.extra==="object"?value.extra as Record<string,unknown>:{};const amount=typeof value.amount==="string"?value.amount:extra.chargedAmount;return typeof value.success==="boolean"?{success:value.success,...(typeof value.transaction==="string"?{transaction:value.transaction}:{}),...(typeof value.network==="string"?{network:value.network}:{}),...(typeof amount==="string"&&/^\d+$/.test(amount)?{amount}:{})}:null;}catch{return null;}}
function errorMessage(e:unknown){return e instanceof Error?e.message:String(e);}

export class PostgresBatchChannelStorage implements ClientChannelStorage{
  constructor(private store:Store,private userId:string){}
  get(key:string){return this.store.getBatchChannel(this.userId,key);}
  set(key:string,context:BatchSettlementClientContext){return this.store.setBatchChannel(this.userId,key,context);}
  delete(key:string){return this.store.deleteBatchChannel(this.userId,key);}
}
