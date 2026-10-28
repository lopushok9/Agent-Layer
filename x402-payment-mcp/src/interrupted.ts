import type { Address, PublicClient } from "viem";
import type { WalletNetwork } from "./transaction-builder.js";
import type { WalletStore } from "./wallet-store.js";

type Repository = Pick<WalletStore, "interruptedOperations" | "failInterrupted">;

// Without this, a crash between reservation and signing, or a swap that failed
// after Permit2 but before its UserOperation, blocked the address forever: no
// hash to reconcile and no nonce to cancel. Must run under withPaymentLock.
export async function resolveInterrupted(store: Repository, rpc: () => Pick<PublicClient, "getBlock">, userId: string, network: WalletNetwork, address: Address) {
  const rows = await store.interruptedOperations(userId, network, address);
  let finalized: bigint | undefined;
  for (const row of rows) {
    if (row.status === "reserved") {
      await store.failInterrupted(userId, row.id, "Execution was interrupted before signing; nothing was signed.");
      continue;
    }
    if (row.permitDeadline === undefined) continue;
    if (row.permitDeadline !== null) {
      // Permit2 SignatureTransfer reverts SignatureExpired once block.timestamp >
      // deadline; a finalized block past it cannot be reorganized back.
      finalized ??= (await rpc().getBlock({ blockTag: "finalized" })).timestamp;
      if (finalized <= row.permitDeadline) continue;
    }
    await store.failInterrupted(userId, row.id, row.permitDeadline === null
      ? "Swap stopped before its UserOperation was signed; no Permit2 authorization was needed."
      : "Swap stopped before its UserOperation was signed; its Permit2 authorization expired unused.");
  }
}
