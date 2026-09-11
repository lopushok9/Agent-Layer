import { isIP } from "node:net";
import dns from "node:dns";
import { Agent, fetch as undiciFetch } from "undici";

function privateAddress(address:string){
  if(address==="::1"||address.startsWith("fc")||address.startsWith("fd")||address.startsWith("fe80:"))return true;
  if(isIP(address)===4){const [a,b=0]=address.split(".").map(Number);return a===10||a===127||a===0||(a===169&&b===254)||(a===172&&b>=16&&b<=31)||(a===192&&b===168);}
  return false;
}

const dispatcher=new Agent({connect:{lookup:((hostname:string,_options:unknown,callback:(error:Error|null,address?:string,family?:number)=>void)=>{dns.lookup(hostname,{all:true},(err,addresses)=>{if(err)return callback(err);if(!addresses.length||addresses.some((x)=>privateAddress(x.address)))return callback(new Error("private network destinations are blocked"));const first=addresses[0]!;callback(null,first.address,first.family);});}) as any}});

export function assertSafeResourceUrl(raw:string):URL{const url=new URL(raw);if(url.protocol!=="https:")throw new Error("Bazaar resource must use HTTPS");if(url.username||url.password||url.port)throw new Error("resource credentials and custom ports are not allowed");if(url.hostname==="localhost"||privateAddress(url.hostname))throw new Error("private network destinations are blocked");return url;}

export const safeFetch:typeof globalThis.fetch=((input:RequestInfo|URL,init?:RequestInit)=>undiciFetch(input as any,{...(init as any),redirect:"error",dispatcher})) as typeof globalThis.fetch;

export async function limitedBody(response:Response,maxBytes=1_000_000):Promise<unknown>{
  const length=Number(response.headers.get("content-length")??0);if(length>maxBytes)throw new Error("resource response is too large");
  if(!response.body)return null;const reader=response.body.getReader();const chunks:Uint8Array[]=[];let size=0;
  while(true){const {done,value}=await reader.read();if(done)break;size+=value.byteLength;if(size>maxBytes){await reader.cancel();throw new Error("resource response is too large");}chunks.push(value);}
  const text=new TextDecoder().decode(Buffer.concat(chunks));if(!text)return null;const type=response.headers.get("content-type")??"";if(type.includes("json")){try{return JSON.parse(text);}catch{return text;}}return text;
}
