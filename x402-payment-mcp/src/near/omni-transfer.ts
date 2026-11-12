import { encodeFunctionData, erc20Abi, getAddress, type Address } from "viem";
import { z } from "zod";
import type { NearAccountService } from "./account.js";
import type { ChainSignatures, EvmNetwork } from "./chain-signatures.js";
import type { IntentsPlan, NearIntents, OneClickToken } from "./intents.js";
import { NearPublicError, type NearOperations } from "./operations.js";
import type { IntentsDeposits } from "./poa-bridge.js";
import { formatUnits, parseUnits } from "./rhea.js";
import type { IntentsTrades } from "./solver-relay.js";
import type { NearStore } from "./store.js";

// omni_transfer: one entry point for moving value between the places this NEAR
// account controls: its NEAR wallet, its NEAR Intents balance and its Chain
// Signatures address on Base/Ethereum. Every route is exactly ONE signed
// operation built by the existing, tested modules; this module only picks it:
//   near -> intents (same token)        ft_transfer_call to intents.near (near_tx)
//   intents -> near (same NEAR token)   withdraw intent via the Solver Relay, no gas
//   near -> anything else               1Click, paid from the wallet
//   intents -> anything else            1Click, paid from the intents balance (relay)
//   base/ethereum -> intents (same)     transfer to the PoA bridge deposit address
//   base/ethereum -> anything else      transfer to a 1Click EVM deposit address
// omni_transfer_execute / omni_transfer_status dispatch on the operation kind.
const LOCATIONS = ["near", "intents", "base", "ethereum"] as const;
type Location = typeof LOCATIONS[number];
const CHAIN: Record<Location, string> = { near: "near", intents: "near", base: "base", ethereum: "eth" };
const DEC = /^\d{1,30}(\.\d{1,36})?$/;

export const omniTransferInput = z.strictObject({
  from: z.enum(LOCATIONS).describe("near: the NEAR wallet; intents: the NEAR Intents balance; base / ethereum: the Chain Signatures EVM address"),
  to: z.enum(LOCATIONS).describe("Destination, same choices; delivery to base/ethereum goes to this account's Chain Signatures EVM address"),
  asset: z.string().min(2).max(200).describe('What to send: a symbol on the source (NEAR, USDC, ETH, ...), SYMBOL@chain, or a 1Click asset id. On intents a bare symbol matches what the intents balance holds'),
  amount: z.string().min(1).max(70).describe('Human amount, e.g. "0.25"'),
  receive_asset: z.string().min(2).max(200).optional().describe("Token to receive at the destination (symbol on the destination chain, SYMBOL@chain or asset id); default: the same token"),
  slippage_bps: z.number().int().min(1).max(500).default(100),
});

export class OmniTransfer {
  constructor(
    private accounts: NearAccountService, private operations: NearOperations, private store: NearStore,
    private intents: NearIntents, private trades: IntentsTrades | null, private cs: ChainSignatures | null, private deposits: IntentsDeposits | null,
  ) {}

  private async tokenAt(ref: string, loc: Location, userId: string): Promise<OneClickToken> {
    const r = ref.trim();
    if (r.includes("@") || r.includes(":")) return this.intents.asset(r, "asset");
    const sym = r.toUpperCase();
    if (loc === "intents") {
      const held = ((await this.intents.balances(userId)) as { balances?: { asset_id: string; symbol?: string }[] }).balances ?? [];
      const hits = held.filter(b => (b.symbol ?? "").toUpperCase() === (sym === "NEAR" ? "WNEAR" : sym));
      if (hits.length === 1) return this.intents.asset(hits[0]!.asset_id, "asset");
      if (hits.length > 1) throw new NearPublicError(`the intents balance holds several ${r.slice(0, 20)} assets (${hits.map(h => h.asset_id).join(", ")}); pass the asset id. Nothing was signed`);
    }
    if (sym === "NEAR" || sym === "WNEAR") {
      if (CHAIN[loc] !== "near") throw new NearPublicError(`NEAR lives on NEAR; on ${loc} pick another token. Nothing was signed`);
      return this.intents.asset("NEAR", "asset");
    }
    return this.intents.asset(`${sym}@${CHAIN[loc]}`, "asset");
  }

  async prepare(userId: string, input: z.input<typeof omniTransferInput>) {
    const p = omniTransferInput.parse(input);
    if (!DEC.test(p.amount.trim())) throw new NearPublicError('amount must be a decimal like "0.25"; nothing was signed');
    const origin = await this.tokenAt(p.asset, p.from, userId);
    // Same token by default; into intents an EVM token stays the bridged asset.
    const dest = p.receive_asset ? await this.tokenAt(p.receive_asset, p.to === "intents" ? "near" : p.to, userId)
      : p.to === "intents" ? origin : await this.tokenAt(origin.symbol.toUpperCase() === "WNEAR" ? "NEAR" : origin.symbol, p.to, userId);
    const amount = parseUnits(p.amount.trim(), origin.decimals);
    if (amount <= 0n) throw new NearPublicError("amount must be positive; nothing was signed");
    const same = origin.assetId === dest.assetId;
    if (p.from === p.to && same) throw new NearPublicError(`${p.amount} ${origin.symbol} is already on ${p.from}; nothing to move. Nothing was signed`);
    const deliver = p.to === "intents" ? "intents" as const : "chain" as const;
    const summary = (route: string, how: string, op: Record<string, unknown>) => ({
      ...op,
      omni_transfer: { route, how, from: p.from, to: p.to, send: { asset_id: origin.assetId, symbol: origin.symbol, amount: amount.toString(), formatted: formatUnits(amount, origin.decimals) }, receive: { asset_id: dest.assetId, symbol: dest.symbol, blockchain: dest.blockchain }, execute_with: "omni_transfer_execute", status_with: "omni_transfer_status" },
      confirmation: "Show omni_transfer (route, send, receive) and the details of the one operation below (amounts, minimum, recipient, fees); after the user confirms call omni_transfer_execute once, then omni_transfer_status until it is final.",
    });

    if (p.from === "near") {
      if (p.to === "intents" && same) return summary("wallet_to_intents", "ft_transfer_call to intents.near from the NEAR wallet (NEAR is wrapped first); one NEAR transaction", await this.intents.prepareDeposit(userId, { asset: origin.assetId, amount: amount.toString() }));
      return summary("oneclick_from_wallet", "1Click: the NEAR wallet sends the token to a 1Click deposit account in one NEAR transaction; solvers deliver at the destination or refund", await this.intents.prepare(userId, { origin_asset: origin.assetId, destination_asset: dest.assetId, amount: amount.toString(), pay_from: "wallet", deliver_to: deliver, slippage_bps: p.slippage_bps }));
    }
    if (p.from === "intents") {
      if (!this.trades) throw new NearPublicError("the Solver Relay is not configured; nothing was signed");
      if (p.to === "near" && same) return summary("intents_to_wallet", "one signed withdraw intent submitted by the Solver Relay (no NEAR gas); NEAR arrives as native NEAR", await this.trades.prepareWithdraw(userId, { asset: dest.assetId === "nep141:wrap.near" ? "NEAR" : dest.assetId, amount: amount.toString() }));
      return summary("oneclick_from_intents", "1Click paid from the intents balance: one signed transfer intent submitted by the Solver Relay (no NEAR gas)", await this.trades.prepareOneClick(userId, { origin_asset: origin.assetId, destination_asset: dest.assetId, amount: amount.toString(), pay_from: "intents", deliver_to: deliver, slippage_bps: p.slippage_bps }));
    }

    // From Base/Ethereum: one EVM transfer signed through Chain Signatures.
    if (!this.cs) throw new NearPublicError("Chain Signatures is not configured; nothing was signed");
    const network = p.from as EvmNetwork;
    if (origin.blockchain !== CHAIN[p.from]) throw new NearPublicError(`${origin.symbol} (${origin.blockchain}) is not a ${p.from} token; nothing was signed`);
    const send = (to: Address) => origin.contractAddress
      ? { network, to: getAddress(origin.contractAddress), data: encodeFunctionData({ abi: erc20Abi, functionName: "transfer", args: [to, amount] }) }
      : { network, to, value_wei: amount.toString() };
    if (p.to === "intents" && same) {
      if (!this.deposits) throw new NearPublicError("the PoA bridge is not configured; nothing was signed");
      const d = await this.deposits.depositAddress(userId, { network });
      const tok = d.tokens.find(t => t.intents_asset_id === origin.assetId);
      if (!tok) throw new NearPublicError(`the PoA bridge does not accept ${origin.symbol} on ${network}; nothing was signed`);
      if (amount < BigInt(tok.min_deposit)) throw new NearPublicError(`below the bridge minimum of ${tok.min_deposit_formatted} ${origin.symbol}; nothing was signed`);
      const deposit = getAddress(d.deposit_address);
      return summary("poa_deposit", `one ${network} transfer to the PoA bridge deposit address assigned to this NEAR account; credited to the intents balance in a few minutes`, await this.cs.prepare(userId, send(deposit), { poa_deposit: { deposit_address: deposit, credited_to: d.credited_to, asset_id: origin.assetId } }, { poa: { deposit_address: deposit, asset_id: origin.assetId, amount: amount.toString() } }));
    }
    const q = await this.intents.quoteFromEvm(userId, { origin, dest, amount: amount.toString(), deliver_to: deliver, slippage_bps: p.slippage_bps });
    return summary("oneclick_from_evm", `one ${network} transfer to a 1Click deposit address; solvers deliver at the destination or refund to the EVM address`, await this.cs.prepare(userId, send(q.plan.deposit_address as Address), { intents: q.description }, { oneclick: q.plan }));
  }

  async execute(userId: string, id: string, purpose: string) {
    const op = await this.store.operation(userId, id);
    if (!op) throw new NearPublicError("operation not found for this user");
    switch (op.kind) {
      case "near_tx": return this.operations.execute(userId, id, purpose);
      case "intents_swap": return this.intents.execute(userId, id, purpose);
      case "intents_trade":
        if (!this.trades) throw new NearPublicError("the Solver Relay is not configured; nothing was signed");
        return this.trades.execute(userId, id, purpose);
      case "chain_signature": {
        if (!this.cs) throw new NearPublicError("Chain Signatures is not configured; nothing was signed");
        const plan = op.plan as { oneclick?: IntentsPlan; poa?: unknown } | null;
        if (!plan?.oneclick && !plan?.poa) throw new NearPublicError("not an omni_transfer operation; use evm_call_execute. Nothing was signed");
        const r = await this.cs.execute(userId, id, purpose) as Record<string, unknown>;
        if (plan.oneclick && typeof r.evm_tx_hash === "string") {
          const submitted = await this.intents.submitDeposit(r.evm_tx_hash, plan.oneclick.deposit_address).then(() => true, () => "not acknowledged (1Click also detects the deposit on its own)");
          return { ...r, oneclick: { deposit_address: plan.oneclick.deposit_address, deposit_submitted: submitted }, next: "Call omni_transfer_status until the EVM receipt is final and 1Click reports SUCCESS or REFUNDED." };
        }
        return { ...r, next: "Call omni_transfer_status until the EVM receipt is final; the bridge then credits the intents balance within minutes (intents_balances)." };
      }
      default: throw new NearPublicError("not an omni_transfer operation; nothing was signed");
    }
  }

  async status(userId: string, id: string) {
    const op = await this.store.operation(userId, id);
    if (!op) throw new NearPublicError("operation not found for this user");
    switch (op.kind) {
      case "near_tx": return this.operations.status(userId, id);
      case "intents_swap": return this.intents.status(userId, id);
      case "intents_trade":
        if (!this.trades) throw new NearPublicError("the Solver Relay is not configured");
        return this.trades.status(userId, id);
      case "chain_signature": {
        if (!this.cs) throw new NearPublicError("Chain Signatures is not configured");
        const evm = await this.cs.operationStatus(userId, id);
        const plan = op.plan as { oneclick?: IntentsPlan } | null;
        if (plan?.oneclick && evm.stage === "evm_final") return { ...evm, oneclick: await this.intents.oneClickStatus(plan.oneclick).catch(() => ({ swap_status: "UNAVAILABLE" })) };
        return evm;
      }
      default: throw new NearPublicError("not an omni_transfer operation");
    }
  }
}
