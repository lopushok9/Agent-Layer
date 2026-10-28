import { Core } from "@walletconnect/core";
import { WalletKit } from "@reown/walletkit";
import type { Pool } from "pg";
import type { Config } from "./config.js";
import type { DappClient } from "./dapps.js";
import { PgKeyValueStorage } from "./walletconnect-storage.js";

// Returns null when WalletConnect is not configured or the client cannot start,
// so the rest of the wallet keeps working without the dApp tools.
export async function walletConnectClient(config: Config, pool: Pool): Promise<DappClient | null> {
  if (!config.WALLETCONNECT_PROJECT_ID || !config.WALLET_OPERATION_ENCRYPTION_KEY) return null;
  try {
    const core = new Core({ projectId: config.WALLETCONNECT_PROJECT_ID, storage: new PgKeyValueStorage(pool, config.WALLET_OPERATION_ENCRYPTION_KEY) as never, logger: "error" });
    return await WalletKit.init({ core: core as never, metadata: { name: "AgentLayer Smart Wallet", description: "Hosted smart account; every app request is previewed and confirmed in chat.", url: config.PUBLIC_BASE_URL, icons: [] } }) as unknown as DappClient;
  } catch (e) {
    console.error(JSON.stringify({ level: "error", event: "walletconnect_start_failed", message: e instanceof Error ? e.message : String(e) }));
    return null;
  }
}
