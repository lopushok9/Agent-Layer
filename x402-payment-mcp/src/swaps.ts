import type { EnsoRoutes } from "./enso-routes.js";
import type { ManagedSwapService } from "./managed-swaps.js";
import { swapInput, type SwapInput } from "./swap-plan.js";
import type { TransactionService } from "./transactions.js";
import { publicWalletError } from "./wallet-errors.js";

type Cdp = Pick<ManagedSwapService, "preview" | "execute"> & Partial<Pick<ManagedSwapService, "operation">>;
type Enso = Pick<EnsoRoutes, "preview">;
type Transactions = Pick<TransactionService, "execute">;

// swap_preview / swap_execute. Enso is asked first: it routes across all DEXs
// and aggregators with no protocol fee (measured on Base ETH->USDC: 0.03-0.3%
// more output than CDP's swap API, which charges 0.15%), and its preview is a
// normal transaction preview with the route's minimum enforced on-chain by
// EnsoRouter.safeRouteSingle and any exact approval in the same batch. CDP's
// managed swap stays as the fallback when Enso is not configured, cannot
// route, or the user asked for zero slippage (Enso needs at least 1 bp).
export class Swaps {
  constructor(private cdp: Cdp, private enso?: Enso, private transactions?: Transactions) {}

  async preview(userId: string, input: SwapInput) {
    const p = swapInput.parse(input);
    let ensoError: string | null = null;
    if (this.enso && p.slippage_bps >= 1) {
      try {
        const r = await this.enso.preview(userId, { network: p.network, token_in: p.from_token, amount_in: p.from_amount_atomic, token_out: p.to_token, slippage_bps: p.slippage_bps });
        return { ...r, provider: "enso", next_step: "Show the route: input, expected and minimum output, hops, price impact, any exact approval in the batch and the simulated asset changes. After the user confirms this exact preview, call swap_execute once with operation_id and purpose. The route reverts on-chain below the minimum output." };
      } catch (e) { ensoError = publicWalletError(e).message; }
    }
    const r = await this.cdp.preview(userId, input);
    return { ...r, provider: "cdp", ...(ensoError ? { enso_unavailable: ensoError } : p.slippage_bps < 1 && this.enso ? { enso_unavailable: "Enso needs a slippage of at least 1 bp" } : {}) };
  }

  // A preview from either provider: an Enso route is an ordinary prepared
  // operation, a CDP swap is a managed swap operation.
  async execute(userId: string, id: string, purpose: string) {
    const op = await this.cdp.operation?.(userId, id);
    const route = op && op.kind !== "swap" ? (op.simulation as { route?: { provider?: unknown; protocol?: unknown } }).route : undefined;
    if (route) {
      if (route.provider !== "enso" || route.protocol !== undefined || !this.transactions) throw new Error("this operation is not a swap preview; use transaction_execute");
      return this.transactions.execute(userId, id, purpose);
    }
    return this.cdp.execute(userId, id, purpose);
  }
}
