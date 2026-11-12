import express from "express";
import { createMcpExpressApp, requireBearerAuth } from "@modelcontextprotocol/express";
import { NodeStreamableHTTPServerTransport } from "@modelcontextprotocol/node";
import { OAuthError, OAuthErrorCode } from "@modelcontextprotocol/server";
import { ManagedSwapService } from "./managed-swaps.js";
import { SmartWalletService } from "./smart-wallet.js";
import { WalletStore } from "./wallet-store.js";
import { TransactionService } from "./transactions.js";
import { createTokenVerifier } from "./auth.js";
import { LinkService, linkRouter } from "./link.js";
import type { Config } from "./config.js";
import { connectorDiagnostics } from "./diagnostics.js";
import { homeRouter } from "./home.js";
import { createUserMcp } from "./mcp.js";
import { oauthRouter } from "./oauth.js";
import { PaymentService } from "./payments.js";
import { TokenService } from "./security.js";
import { Store } from "./store.js";
import { RegistryContractMetadata, type ContractMetadata } from "./contract-metadata.js";
import { SignatureService } from "./signatures.js";
import { DappService } from "./dapps.js";
import { DappStore } from "./dapp-store.js";
import { walletConnectClient } from "./walletconnect.js";
import { EnsoRoutes } from "./enso-routes.js";
import { EnsoCatalog } from "./enso-catalog.js";
import { alchemyKey, Portfolio } from "./portfolio.js";
import { Nfts } from "./nfts.js";
import { WalletHistory } from "./history.js";
import { Names } from "./names.js";
import { NameRegistration } from "./name-registration.js";
import { tokenManagerRouter } from "./token-manager.js";
import { NEAR_SCOPE } from "./security.js";
import { loadNearConfig } from "./near/config.js";
import { NearStore } from "./near/store.js";
import { NearRpc } from "./near/rpc.js";
import { NearAccountService } from "./near/account.js";
import { NearOperations } from "./near/operations.js";
import { ChainSignatures } from "./near/chain-signatures.js";
import { EvmSwaps } from "./near/swap.js";
import { NearIntents, OneClickClient } from "./near/intents.js";
import { IntentsTrades, SolverRelayClient } from "./near/solver-relay.js";
import { IntentsDeposits } from "./near/poa-bridge.js";
import { OmniBalances } from "./near/balances.js";
import { YieldSearch } from "./near/yields.js";
import { createNearMcp, type NearServices } from "./near/mcp.js";

// NEAR Omni Account: independent product on its own MCP resource (/near/mcp).
// Enabled only by NEAR_RPC_URL; it reuses login, the database and the
// deployment-owned EVM RPCs, and never touches the smart wallet or x402 paths.
function nearServices(config:Config,store:Store,wallets:SmartWalletService,contracts:ContractMetadata|null=null):NearServices|null{
  const near=loadNearConfig();if(!near)return null;
  const nearStore=new NearStore(store.pool);const accounts=new NearAccountService(near,nearStore,new NearRpc(near.rpcUrl,near.network),wallets.cdp.solana);
  const operations=new NearOperations(accounts,nearStore);
  // Chain Signatures target Base/Ethereum mainnet, so they run only for NEAR mainnet.
  const chainSignatures=new ChainSignatures(accounts,operations,nearStore,network=>{if(near.network!=="mainnet")throw new Error("evm Chain Signatures require NEAR mainnet");return wallets.rpc(network);},contracts);
  if(!config.nearEnabled)throw new Error("NEAR configuration mismatch");
  const intents=new NearIntents(accounts,operations,nearStore,chainSignatures,new OneClickClient(undefined,undefined,process.env.ONECLICK_JWT||undefined));
  return{accounts,operations,chainSignatures,swaps:new EvmSwaps(chainSignatures),intents,trades:new IntentsTrades(accounts,nearStore,intents,new SolverRelayClient(undefined,undefined,process.env.SOLVER_RELAY_API_KEY||undefined)),deposits:new IntentsDeposits(accounts,chainSignatures),balances:new OmniBalances(accounts,intents,chainSignatures),yields:new YieldSearch(accounts,intents,chainSignatures)};
}

export async function createApp(config:Config){
  const store=new Store(config.DATABASE_URL);await store.migrate();await store.startOAuthCleanup();const tokens=await TokenService.create(config);const walletStore=new WalletStore(store.pool,config.WALLET_OPERATION_ENCRYPTION_KEY);const wallets=new SmartWalletService(config,walletStore);const names=config.ETHEREUM_RPC_URL?new Names(network=>wallets.rpc(network)):null;const contracts=new RegistryContractMetadata(network=>wallets.rpc(network),{...(config.ETHERSCAN_API_KEY?{etherscanApiKey:config.ETHERSCAN_API_KEY}:{})});const transactions=new TransactionService(wallets,walletStore,store,config.PREVIEW_TTL_SECONDS,contracts,names);const signatures=new SignatureService(wallets,walletStore,config.PREVIEW_TTL_SECONDS,contracts);const walletKit=await walletConnectClient(config,store.pool);const dapps=walletKit?new DappService(walletKit,new DappStore(store.pool),wallets,transactions,signatures):undefined;const routes=config.ENSO_API_KEY?new EnsoRoutes(wallets,transactions,config.ENSO_API_KEY):undefined;const catalog=routes?new EnsoCatalog(routes.api):undefined;const rpcUrl=(network:"base"|"ethereum")=>network==="base"?config.BASE_RPC_URL:config.ETHEREUM_RPC_URL;const hasAlchemy=Boolean(alchemyKey(config.BASE_RPC_URL)||alchemyKey(config.ETHEREUM_RPC_URL));const history=new WalletHistory(wallets,rpcUrl);const portfolio=routes?new Portfolio(routes.api,wallets,rpcUrl,fetch,Date.now,history):undefined;const nfts=hasAlchemy?new Nfts(wallets,rpcUrl):undefined;const nameRegistration=config.BASE_RPC_URL?new NameRegistration(wallets,(userId,input)=>transactions.prepare(userId,input)):undefined;const swaps=new ManagedSwapService(wallets,walletStore,store,config.PREVIEW_TTL_SECONDS);const payments=new PaymentService(config,store,tokens,wallets);const link=config.link?new LinkService(config.issuer,config.link,store):null;
  const hostname=new URL(config.PUBLIC_BASE_URL).hostname;
  // The outer app logs failed connector requests before any inner middleware
  // (including the MCP host-header check) can reject them.
  const outer=express();outer.set("trust proxy",1);outer.disable("x-powered-by");outer.use(connectorDiagnostics);
  const app=createMcpExpressApp({host:"0.0.0.0",allowedHosts:[hostname,"localhost","127.0.0.1"],jsonLimit:"256kb"});
  outer.use(app);
  app.set("trust proxy",1);
  app.use(express.urlencoded({extended:false,limit:"32kb"}));
  app.use(oauthRouter(config,store,tokens,link));
  if(link)app.use(linkRouter(link,config,store,tokens));
  app.use(homeRouter(config));
  app.get("/healthz",async(_req,res)=>{try{await store.pool.query("SELECT 1");res.json({ok:true});}catch{res.status(503).json({ok:false});}});
  app.use(tokenManagerRouter(config,store,tokens));
  const verifier=createTokenVerifier(config,tokens,store);
  const auth=requireBearerAuth({verifier,requiredScopes:[],resourceMetadataUrl:`${config.issuer}/.well-known/oauth-protected-resource/mcp`});
  app.post("/mcp",auth,async(req,res,next)=>{try{const authInfo=(req as typeof req&{auth?:{scopes?:string[];extra?:Record<string,unknown>}}).auth;const userId=authInfo?.extra?.userId;if(typeof userId!=="string")throw new OAuthError(OAuthErrorCode.InvalidToken,"token has no user identity");const server=createUserMcp(userId,payments,link,wallets,transactions,authInfo?.scopes??[],swaps,{signatures,...(dapps?{dapps}:{}),...(routes?{routes}:{}),...(catalog?{catalog}:{}),...(portfolio?{portfolio}:{}),...(names?{names}:{}),...(nfts?{nfts}:{}),...(nameRegistration?{nameRegistration}:{}),...(hasAlchemy?{history}:{})});const transport=new NodeStreamableHTTPServerTransport({sessionIdGenerator:undefined});await server.connect(transport);await transport.handleRequest(req,res,req.body);}catch(e){next(e);}});
  app.all("/mcp",(_req,res)=>res.status(405).set("Allow","POST").end());
  const near=nearServices(config,store,wallets,contracts);
  if(near){
    const nearAuth=requireBearerAuth({verifier:createTokenVerifier(config,tokens,store,config.nearResource),requiredScopes:[NEAR_SCOPE],resourceMetadataUrl:`${config.issuer}/.well-known/oauth-protected-resource/near/mcp`});
    app.post("/near/mcp",nearAuth,async(req,res,next)=>{try{const authInfo=(req as typeof req&{auth?:{extra?:Record<string,unknown>}}).auth;const userId=authInfo?.extra?.userId;if(typeof userId!=="string")throw new OAuthError(OAuthErrorCode.InvalidToken,"token has no user identity");const server=createNearMcp(userId,near);const transport=new NodeStreamableHTTPServerTransport({sessionIdGenerator:undefined});await server.connect(transport);await transport.handleRequest(req,res,req.body);}catch(e){next(e);}});
    app.all("/near/mcp",(_req,res)=>res.status(405).set("Allow","POST").end());
  }
  app.use((err:unknown,_req:express.Request,res:express.Response,_next:express.NextFunction)=>{console.error(err);if(res.headersSent)return;res.status(500).json({error:"server_error",error_description:"The request could not be completed"});});
  return{app:outer,store};
}
