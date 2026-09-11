import { z } from "zod";

const Env = z.object({
  PUBLIC_BASE_URL: z.string().url().transform((v) => v.replace(/\/$/, "")),
  MCP_DANGEROUSLY_ALLOW_INSECURE_ISSUER_URL: z.enum(["true","1","false","0"]).default("false").transform(v=>v==="true"||v==="1"),
  PORT: z.coerce.number().int().positive().default(3000),
  DATABASE_URL: z.string().min(1),
  OAUTH_SIGNING_PRIVATE_JWK: z.string().min(1),
  GOOGLE_CLIENT_ID: z.string().min(1),
  GOOGLE_CLIENT_SECRET: z.string().min(1),
  GITHUB_CLIENT_ID: z.string().min(1),
  GITHUB_CLIENT_SECRET: z.string().min(1),
  CDP_API_KEY_ID: z.string().min(1),
  CDP_API_KEY_SECRET: z.string().min(1),
  CDP_WALLET_SECRET: z.string().min(1),
  ACCESS_TOKEN_TTL_SECONDS: z.coerce.number().int().min(300).max(3600).default(900),
  REFRESH_TOKEN_TTL_SECONDS: z.coerce.number().int().min(3600).default(2592000),
  AUTH_CODE_TTL_SECONDS: z.coerce.number().int().min(60).max(600).default(300),
  PREVIEW_TTL_SECONDS: z.coerce.number().int().min(30).max(600).default(120),
  MAX_PAYMENT_USDC_ATOMIC: z.string().regex(/^\d+$/).default("1000000"),
  MAX_DAILY_USDC_ATOMIC: z.string().regex(/^\d+$/).default("5000000"),
  PAYMENT_TIMEOUT_MS: z.coerce.number().int().min(1000).max(60000).default(15000),
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
  return { ...value, privateJwk, issuer: value.PUBLIC_BASE_URL, resource };
}

export const BASE_NETWORK = "eip155:8453" as const;
export const BASE_USDC = "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913" as const;
