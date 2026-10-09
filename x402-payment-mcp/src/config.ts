import { z } from "zod";

const Env = z.object({
  PUBLIC_BASE_URL: z.string().url().transform((v) => v.replace(/\/$/, "")),
  MCP_DANGEROUSLY_ALLOW_INSECURE_ISSUER_URL: z.enum(["true","1","false","0"]).default("false").transform(v=>v==="true"||v==="1"),
  PORT: z.coerce.number().int().positive().default(3000),
  DATABASE_URL: z.string().min(1),
  OAUTH_SIGNING_PRIVATE_JWK: z.string().min(1),
  GOOGLE_CLIENT_ID: z.string().min(1).optional(),
  GOOGLE_CLIENT_SECRET: z.string().min(1).optional(),
  GITHUB_CLIENT_ID: z.string().min(1).optional(),
  GITHUB_CLIENT_SECRET: z.string().min(1).optional(),
  CDP_API_KEY_ID: z.string().min(1),
  CDP_API_KEY_SECRET: z.string().min(1),
  CDP_WALLET_SECRET: z.string().min(1),
  ACCESS_TOKEN_TTL_SECONDS: z.coerce.number().int().min(300).max(3600).default(900),
  REFRESH_TOKEN_TTL_SECONDS: z.coerce.number().int().min(3600).default(2592000),
  AUTH_CODE_TTL_SECONDS: z.coerce.number().int().min(60).max(600).default(300),
  PERSONAL_TOKEN_TTL_DAYS: z.coerce.number().int().min(1).max(365).default(90),
  PERSONAL_TOKEN_MAX_ACTIVE: z.coerce.number().int().min(1).max(50).default(10),
  // The user has to read the preview and approve the payment in a chat UI
  // before the agent can call x402_pay, which routinely takes over two minutes.
  PREVIEW_TTL_SECONDS: z.coerce.number().int().min(30).max(600).default(600),
  SPEND_LIMITS_ENABLED: z.enum(["true","1","false","0"]).default("false").transform(v=>v==="true"||v==="1"),
  MAX_PAYMENT_USDC_ATOMIC: z.string().regex(/^\d+$/).default("1000000"),
  MAX_DAILY_USDC_ATOMIC: z.string().regex(/^\d+$/).default("5000000"),
  // Deployment-owned secret. Do not fall back to a public RPC for a service
  // that signs and broadcasts mainnet USDC transfers.
  ARC_RPC_URL: z.string().url(),
  ARC_MAX_TRANSFER_USDC_ATOMIC: z.string().regex(/^\d+$/).default("50000000"),
  ARC_MAX_DAILY_TRANSFER_USDC_ATOMIC: z.string().regex(/^\d+$/).default("200000000"),
  PAYMENT_TIMEOUT_MS: z.coerce.number().int().min(1000).max(60000).default(45000),
  // Optional Link Agent Wallet. All four are set together or not at all; the
  // registered redirect URI is always ${PUBLIC_BASE_URL}/auth/link/callback.
  LINK_CLIENT_ID: z.string().min(1).optional(),
  LINK_CLIENT_SECRET: z.string().min(1).optional(),
  STRIPE_PUBLISHABLE_KEY: z.string().regex(/^pk_(live|test)_[A-Za-z0-9]+$/,"STRIPE_PUBLISHABLE_KEY must be a Stripe publishable key (pk_live_… or pk_test_…), never a secret key").optional(),
  // 32 random bytes, base64. Encrypts stored Link tokens; rotating it disconnects every Link wallet.
  LINK_TOKEN_ENCRYPTION_KEY: z.string().min(1).optional(),
}).superRefine((value,ctx)=>{
  const google=Boolean(value.GOOGLE_CLIENT_ID&&value.GOOGLE_CLIENT_SECRET);
  const github=Boolean(value.GITHUB_CLIENT_ID&&value.GITHUB_CLIENT_SECRET);
  if(Boolean(value.GOOGLE_CLIENT_ID)!==Boolean(value.GOOGLE_CLIENT_SECRET))ctx.addIssue({code:"custom",message:"Google OAuth requires both client ID and secret"});
  if(Boolean(value.GITHUB_CLIENT_ID)!==Boolean(value.GITHUB_CLIENT_SECRET))ctx.addIssue({code:"custom",message:"GitHub OAuth requires both client ID and secret"});
  if(!google&&!github)ctx.addIssue({code:"custom",message:"At least one OAuth provider must be configured"});
  const link=[value.LINK_CLIENT_ID,value.LINK_CLIENT_SECRET,value.STRIPE_PUBLISHABLE_KEY,value.LINK_TOKEN_ENCRYPTION_KEY].filter(Boolean).length;
  if(link!==0&&link!==4)ctx.addIssue({code:"custom",message:"Link requires LINK_CLIENT_ID, LINK_CLIENT_SECRET, STRIPE_PUBLISHABLE_KEY and LINK_TOKEN_ENCRYPTION_KEY together"});
  if(value.LINK_TOKEN_ENCRYPTION_KEY&&Buffer.from(value.LINK_TOKEN_ENCRYPTION_KEY,"base64").length!==32)ctx.addIssue({code:"custom",message:"LINK_TOKEN_ENCRYPTION_KEY must be 32 random bytes encoded as base64"});
});

export type Config = ReturnType<typeof loadConfig>;

export function loadConfig(env: NodeJS.ProcessEnv = process.env) {
  const value = Env.parse(env);
  const publicUrl=new URL(value.PUBLIC_BASE_URL);
  if(publicUrl.protocol!=="https:"&&!(value.MCP_DANGEROUSLY_ALLOW_INSECURE_ISSUER_URL&&["localhost","127.0.0.1","::1"].includes(publicUrl.hostname))){
    throw new Error("PUBLIC_BASE_URL must use HTTPS (insecure mode is allowed only for loopback development)");
  }
  const privateJwk = JSON.parse(value.OAUTH_SIGNING_PRIVATE_JWK) as JsonWebKey;
  if (privateJwk.kty !== "EC" || privateJwk.crv !== "P-256" || !privateJwk.d) {
    throw new Error("OAUTH_SIGNING_PRIVATE_JWK must be a private P-256 JWK");
  }
  const resource = `${value.PUBLIC_BASE_URL}/mcp`;
  return { ...value, privateJwk, issuer: value.PUBLIC_BASE_URL, resource, link: linkConfig(value) };
}

export type LinkConfig = { clientId: string; clientSecret: string; publishableKey: string; encryptionKey: Buffer };
function linkConfig(value: z.infer<typeof Env>): LinkConfig | null {
  if (!value.LINK_CLIENT_ID || !value.LINK_CLIENT_SECRET || !value.STRIPE_PUBLISHABLE_KEY || !value.LINK_TOKEN_ENCRYPTION_KEY) return null;
  return { clientId: value.LINK_CLIENT_ID, clientSecret: value.LINK_CLIENT_SECRET, publishableKey: value.STRIPE_PUBLISHABLE_KEY, encryptionKey: Buffer.from(value.LINK_TOKEN_ENCRYPTION_KEY, "base64") };
}

export const BASE_NETWORK = "eip155:8453" as const;
export const BASE_USDC = "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913" as const;
// Arc mainnet: USDC is the native gas asset; transfers use its 6-decimal
// ERC-20 interface at this system address.
export const ARC_CHAIN_ID = 5042 as const;
export const ARC_NETWORK = "eip155:5042" as const;
export const ARC_USDC = "0x3600000000000000000000000000000000000000" as const;
