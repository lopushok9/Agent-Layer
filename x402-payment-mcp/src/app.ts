import express from "express";
import { createMcpExpressApp, requireBearerAuth } from "@modelcontextprotocol/express";
import { NodeStreamableHTTPServerTransport } from "@modelcontextprotocol/node";
import { OAuthError, OAuthErrorCode, type OAuthTokenVerifier } from "@modelcontextprotocol/server";
import type { Config } from "./config.js";
import { createUserMcp } from "./mcp.js";
import { oauthRouter } from "./oauth.js";
import { PaymentService } from "./payments.js";
import { TokenService } from "./security.js";
import { Store } from "./store.js";

export async function createApp(config:Config){
  const store=new Store(config.DATABASE_URL);const tokens=await TokenService.create(config);const payments=new PaymentService(config,store,tokens);
  const hostname=new URL(config.PUBLIC_BASE_URL).hostname;
  const app=createMcpExpressApp({host:"0.0.0.0",allowedHosts:[hostname,"localhost","127.0.0.1"],jsonLimit:"256kb"});
  app.use(express.urlencoded({extended:false,limit:"32kb"}));
  app.use(oauthRouter(config,store,tokens));
  app.get("/healthz",async(_req,res)=>{try{await store.pool.query("SELECT 1");res.json({ok:true});}catch{res.status(503).json({ok:false});}});
  const verifier:OAuthTokenVerifier={async verifyAccessToken(token){try{const v=await tokens.verifyAccessToken(token);return{token,clientId:v.clientId,scopes:v.scopes,expiresAt:v.expiresAt,resource:new URL(config.resource),extra:{userId:v.userId}};}catch{throw new OAuthError(OAuthErrorCode.InvalidToken,"invalid or expired access token");}}};
  const auth=requireBearerAuth({verifier,requiredScopes:["x402:pay"],resourceMetadataUrl:`${config.issuer}/.well-known/oauth-protected-resource/mcp`});
  app.post("/mcp",auth,async(req,res,next)=>{try{const authInfo=(req as typeof req&{auth?:{extra?:Record<string,unknown>}}).auth;const userId=authInfo?.extra?.userId;if(typeof userId!=="string")throw new OAuthError(OAuthErrorCode.InvalidToken,"token has no user identity");const server=createUserMcp(userId,payments);const transport=new NodeStreamableHTTPServerTransport({sessionIdGenerator:undefined});await server.connect(transport);await transport.handleRequest(req,res,req.body);}catch(e){next(e);}});
  app.all("/mcp",(_req,res)=>res.status(405).set("Allow","POST").end());
  app.use((err:unknown,_req:express.Request,res:express.Response,_next:express.NextFunction)=>{console.error(err);if(res.headersSent)return;res.status(500).json({error:"server_error",error_description:"The request could not be completed"});});
  return{app,store};
}
