import { isIP } from "node:net";
import dns from "node:dns";
import { Agent, fetch as undiciFetch } from "undici";
import ipaddr from "ipaddr.js";

function publicAddress(address:string){
  const normalized=address.startsWith("[")&&address.endsWith("]")?address.slice(1,-1):address;
  if(!isIP(normalized)||!ipaddr.isValid(normalized))return false;
  const parsed=ipaddr.parse(normalized);const candidate=parsed instanceof ipaddr.IPv6&&parsed.isIPv4MappedAddress()?parsed.toIPv4Address():parsed;
  return candidate.range()==="unicast";
}

const dispatcher=new Agent({connect:{lookup:((hostname:string,_options:unknown,callback:(error:Error|null,address?:string,family?:number)=>void)=>{dns.lookup(hostname,{all:true},(err,addresses)=>{if(err)return callback(err);if(!addresses.length||addresses.some((x)=>!publicAddress(x.address)))return callback(new Error("non-public network destinations are blocked"));const first=addresses[0]!;callback(null,first.address,first.family);});}) as any}});

export function assertSafeResourceUrl(raw:string):URL{const url=new URL(raw);if(url.protocol!=="https:")throw new Error("Bazaar resource must use HTTPS");if(url.username||url.password||url.port)throw new Error("resource credentials and custom ports are not allowed");if(url.hostname==="localhost"||(isIP(url.hostname.replace(/^\[|\]$/g,""))&&!publicAddress(url.hostname)))throw new Error("non-public network destinations are blocked");return url;}

export const safeFetch:typeof globalThis.fetch=(async(input:RequestInfo|URL,init?:RequestInit)=>limitResponseBody(await undiciFetch(input as any,{...(init as any),redirect:"error",dispatcher}) as unknown as Response)) as typeof globalThis.fetch;

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
