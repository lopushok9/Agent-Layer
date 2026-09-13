import { isIP } from "node:net";
import dns from "node:dns";
import { Agent, fetch as undiciFetch } from "undici";
import ipaddr from "ipaddr.js";

type LookupAll=(hostname:string,options:{all:true;verbatim:true},callback:(error:NodeJS.ErrnoException|null,addresses:dns.LookupAddress[])=>void)=>void;
type LookupCallback=(error:NodeJS.ErrnoException|null,address?:string|dns.LookupAddress[],family?:number)=>void;

function publicAddress(address:string){
  const normalized=address.startsWith("[")&&address.endsWith("]")?address.slice(1,-1):address;
  if(!isIP(normalized)||!ipaddr.isValid(normalized))return false;
  const parsed=ipaddr.parse(normalized);const candidate=parsed instanceof ipaddr.IPv6&&parsed.isIPv4MappedAddress()?parsed.toIPv4Address():parsed;
  return candidate.range()==="unicast";
}

export function createPublicLookup(resolver:LookupAll=dns.lookup as unknown as LookupAll){return(hostname:string,options:{all?:boolean},callback:LookupCallback)=>{resolver(hostname,{all:true,verbatim:true},(error,addresses)=>{if(error)return callback(error);if(!addresses.length||addresses.some(address=>!publicAddress(address.address)))return callback(new Error("non-public network destinations are blocked"));if(options.all)return callback(null,addresses);const first=addresses[0]!;return callback(null,first.address,first.family);});};}

const dispatcher=new Agent({connect:{lookup:createPublicLookup() as any}});

export function assertSafeResourceUrl(raw:string):URL{const url=new URL(raw);if(url.protocol!=="https:")throw new Error("Bazaar resource must use HTTPS");if(url.username||url.password||url.port)throw new Error("resource credentials and custom ports are not allowed");if(url.hostname==="localhost"||(isIP(url.hostname.replace(/^\[|\]$/g,""))&&!publicAddress(url.hostname)))throw new Error("non-public network destinations are blocked");return url;}

export async function normalizeUndiciRequest(input:RequestInfo|URL,init?:RequestInit):Promise<{input:string|URL;init:RequestInit}>{
  if(!(input instanceof Request))return{input,init:init??{}};
  const method=init?.method??input.method;const headers=init?.headers??input.headers;const signal=init?.signal??input.signal;const hasBody=method!=="GET"&&method!=="HEAD";const suppliedBody=!!init&&Object.prototype.hasOwnProperty.call(init,"body");const body=hasBody?(suppliedBody?init!.body:await input.arrayBuffer()):undefined;
  return{input:input.url,init:{...init,method,headers,signal,...(body!==undefined&&body!==null?{body}: {})}};
}

export const safeFetch:typeof globalThis.fetch=(async(input:RequestInfo|URL,init?:RequestInit)=>{const normalized=await normalizeUndiciRequest(input,init);return limitResponseBody(await undiciFetch(normalized.input as any,{...(normalized.init as any),redirect:"error",dispatcher}) as unknown as Response);}) as typeof globalThis.fetch;

export function limitResponseBody(response:Response,maxBytes=1_000_000):Response{
  const length=Number(response.headers.get("content-length")??0);if(length>maxBytes){void response.body?.cancel();throw new Error("resource response is too large");}
  if(!response.body)return response;const reader=response.body.getReader();let size=0;
  const body=new ReadableStream<Uint8Array>({async pull(controller){try{const {done,value}=await reader.read();if(done){controller.close();return;}size+=value.byteLength;if(size>maxBytes){await reader.cancel();controller.error(new Error("resource response is too large"));return;}controller.enqueue(value);}catch(error){controller.error(error);}},cancel(reason){return reader.cancel(reason);}});
  return new Response(body,{status:response.status,statusText:response.statusText,headers:response.headers});
}

export async function limitedBody(response:Response,maxBytes=1_000_000):Promise<unknown>{
  const length=Number(response.headers.get("content-length")??0);if(length>maxBytes)throw new Error("resource response is too large");
  if(!response.body)return null;const reader=response.body.getReader();const chunks:Uint8Array[]=[];let size=0;
  while(true){const {done,value}=await reader.read();if(done)break;size+=value.byteLength;if(size>maxBytes){await reader.cancel();throw new Error("resource response is too large");}chunks.push(value);}
  const text=new TextDecoder().decode(Buffer.concat(chunks));if(!text)return null;const type=response.headers.get("content-type")??"";if(type.includes("json")){try{return JSON.parse(text);}catch{return text;}}return text;
}
