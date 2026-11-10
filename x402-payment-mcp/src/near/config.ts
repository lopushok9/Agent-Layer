import { z } from "zod";

// NEAR Omni Account configuration. Independent from the Base smart wallet: the
// feature is enabled only when NEAR_RPC_URL is set, and nothing here changes
// existing wallet, x402 or OAuth behaviour.
const NearEnv = z.object({
  NEAR_RPC_URL: z.string().url().optional(),
  NEAR_NETWORK: z.enum(["mainnet", "testnet"]).default("mainnet"),
  // The key type decides the account address. It is recorded per account and
  // never switched for an existing account.
  NEAR_SIGNER: z.enum(["sealed_key", "cdp_solana"]).default("sealed_key"),
  NEAR_CDP_MESSAGE_ENCODING: z.enum(["base64", "hex", "utf8"]).default("base64"),
  NEAR_KEY_ENCRYPTION_KEY: z.string().optional().refine(v => !v || Buffer.from(v, "base64").length === 32, "NEAR_KEY_ENCRYPTION_KEY must be 32 random bytes encoded as base64"),
  NEAR_MPC_CONTRACT: z.string().min(2).max(64).optional(),
  PREVIEW_TTL_SECONDS: z.coerce.number().int().min(30).max(600).default(600),
}).superRefine((v, ctx) => {
  if (v.NEAR_RPC_URL && v.NEAR_SIGNER === "sealed_key" && !v.NEAR_KEY_ENCRYPTION_KEY) ctx.addIssue({ code: "custom", message: "NEAR_SIGNER=sealed_key requires NEAR_KEY_ENCRYPTION_KEY" });
  if (v.NEAR_RPC_URL && !v.NEAR_RPC_URL.startsWith("https://")) ctx.addIssue({ code: "custom", message: "NEAR_RPC_URL must use HTTPS" });
});

export type NearConfig = {
  rpcUrl: string; network: "mainnet" | "testnet"; signer: "sealed_key" | "cdp_solana";
  cdpMessageEncoding: "base64" | "hex" | "utf8"; keyEncryptionKey: string | undefined;
  mpcContract: string; previewTtlSeconds: number;
};

export const MPC_CONTRACTS = { mainnet: "v1.signer", testnet: "v1.signer-prod.testnet" } as const;

export function loadNearConfig(env: NodeJS.ProcessEnv = process.env): NearConfig | null {
  const v = NearEnv.parse(env);
  if (!v.NEAR_RPC_URL) return null;
  return { rpcUrl: v.NEAR_RPC_URL, network: v.NEAR_NETWORK, signer: v.NEAR_SIGNER, cdpMessageEncoding: v.NEAR_CDP_MESSAGE_ENCODING, keyEncryptionKey: v.NEAR_KEY_ENCRYPTION_KEY, mpcContract: v.NEAR_MPC_CONTRACT ?? MPC_CONTRACTS[v.NEAR_NETWORK], previewTtlSeconds: v.PREVIEW_TTL_SECONDS };
}
