import express from "express";
import { createMcpExpressApp, requireBearerAuth } from "@modelcontextprotocol/express";
import { NodeStreamableHTTPServerTransport } from "@modelcontextprotocol/node";
import { OAuthError, OAuthErrorCode } from "@modelcontextprotocol/server";
import { ArcService } from "./arc.js";
import { createTokenVerifier } from "./auth.js";
import type { Config } from "./config.js";
import { connectorDiagnostics } from "./diagnostics.js";
import { createUserMcp } from "./mcp.js";
import { oauthRouter } from "./oauth.js";
import { PaymentService } from "./payments.js";
import { TokenService } from "./security.js";
import { Store } from "./store.js";
import { tokenManagerRouter } from "./token-manager.js";

export async function createApp(config:Config){
  const store=new Store(config.DATABASE_URL);await store.migrate();await store.startOAuthCleanup();const tokens=await TokenService.create(config);const payments=new PaymentService(config,store,tokens);const arc=ArcService.create(config,store,(userId)=>payments.account(userId));
  const hostname=new URL(config.PUBLIC_BASE_URL).hostname;
  // The outer app logs failed connector requests before any inner middleware
  // (including the MCP host-header check) can reject them.
  const outer=express();outer.set("trust proxy",1);outer.disable("x-powered-by");outer.use(connectorDiagnostics);
  const app=createMcpExpressApp({host:"0.0.0.0",allowedHosts:[hostname,"localhost","127.0.0.1"],jsonLimit:"256kb"});
  outer.use(app);
  app.set("trust proxy",1);
  app.use(express.urlencoded({extended:false,limit:"32kb"}));
  app.use(oauthRouter(config,store,tokens));
  app.get("/healthz",async(_req,res)=>{try{await store.pool.query("SELECT 1");res.json({ok:true});}catch{res.status(503).json({ok:false});}});
  app.use(tokenManagerRouter(config,store,tokens));
  const verifier=createTokenVerifier(config,tokens,store);
  const auth=requireBearerAuth({verifier,requiredScopes:["x402:pay"],resourceMetadataUrl:`${config.issuer}/.well-known/oauth-protected-resource/mcp`});
  app.post("/mcp",auth,async(req,res,next)=>{try{const authInfo=(req as typeof req&{auth?:{extra?:Record<string,unknown>}}).auth;const userId=authInfo?.extra?.userId;if(typeof userId!=="string")throw new OAuthError(OAuthErrorCode.InvalidToken,"token has no user identity");const server=createUserMcp(userId,payments,arc);const transport=new NodeStreamableHTTPServerTransport({sessionIdGenerator:undefined});await server.connect(transport);await transport.handleRequest(req,res,req.body);}catch(e){next(e);}});
  app.all("/mcp",(_req,res)=>res.status(405).set("Allow","POST").end());
  app.use((err:unknown,_req:express.Request,res:express.Response,_next:express.NextFunction)=>{console.error(err);if(res.headersSent)return;res.status(500).json({error:"server_error",error_description:"The request could not be completed"});});
  return{app:outer,store};
}
