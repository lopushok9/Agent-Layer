import { McpServer } from "@modelcontextprotocol/server";
import { z } from "zod";
import { PaymentService } from "./payments.js";

const text=(value:unknown)=>({content:[{type:"text" as const,text:JSON.stringify(value,null,2)}],structuredContent:value as Record<string,unknown>});
const failure=(error:unknown)=>({isError:true,content:[{type:"text" as const,text:error instanceof Error?error.message:String(error)}]});

export function createUserMcp(userId:string,payments:PaymentService){
  const server=new McpServer({name:"AgentLayer x402 Payments",version:"0.1.0"});
  server.registerTool("wallet_status",{title:"Base wallet status",description:"Return the authenticated user's CDP-managed Base wallet address, USDC balance, and spend limits.",inputSchema:z.object({}),annotations:{readOnlyHint:true}},async()=>{try{return text(await payments.walletStatus(userId));}catch(e){return failure(e);}});
  server.registerTool("x402_search",{title:"Search CDP Bazaar",description:"Search CDP Bazaar for eligible x402 v2 services payable with canonical USDC on Base. Returns signed service_ref values; payment tools never accept arbitrary destination URLs.",inputSchema:z.object({query:z.string().min(1).max(400),limit:z.number().int().min(1).max(20).default(10)}),annotations:{readOnlyHint:true}},async({query,limit})=>{try{return text(await payments.search(query,limit));}catch(e){return failure(e);}});
  server.registerTool("x402_preview",{title:"Preview x402 payment",description:"Probe a service returned by x402_search and create a short-lived preview bound to the exact request and payment terms. This does not sign or spend.",inputSchema:z.object({service_ref:z.string().min(20),method:z.enum(["GET","POST"]).default("GET"),body:z.unknown().optional()}),annotations:{readOnlyHint:true}},async({service_ref,method,body})=>{try{return text(await payments.preview(userId,service_ref,{method,body}));}catch(e){return failure(e);}});
  server.registerTool("x402_pay",{title:"Execute previewed x402 payment",description:"Consume one short-lived preview and make exactly one Base USDC x402 payment. Terms are checked again immediately before CDP signs. A purpose is required for the audit log.",inputSchema:z.object({preview_id:z.string().uuid(),purpose:z.string().min(3).max(500)}),annotations:{destructiveHint:true}},async({preview_id,purpose})=>{try{return text(await payments.pay(userId,preview_id,purpose));}catch(e){return failure(e);}});
  return server;
}
