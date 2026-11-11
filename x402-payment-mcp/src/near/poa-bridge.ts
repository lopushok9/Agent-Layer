import { getAddress, isAddress } from "viem";
import { z } from "zod";
import type { NearAccountService } from "./account.js";
import type { ChainSignatures } from "./chain-signatures.js";
import { NearPublicError } from "./operations.js";

// Deposits from Base/Ethereum into this NEAR account's NEAR Intents balance via
// the PoA bridge (the bridge behind near-intents.org deposits): the bridge
// assigns a deposit address to the NEAR account and credits whatever arrives
// there as omft tokens on intents.near. Read only; the transfer itself is an
// ordinary evm_call_prepare from the Chain Signatures address.
export const POA_BRIDGE_URL = "https://bridge.chaindefuser.com/rpc";
const CHAINS = { base: "eth:8453", ethereum: "eth:1" } as const;
const UINT = /^\d{1,78}$/;

export const intentsDepositAddressInput = z.strictObject({
  network: z.enum(["base", "ethereum"]).describe("EVM network the funds are sent from"),
  asset: z.string().min(1).max(20).optional().describe("Filter by symbol, e.g. ETH or USDC"),
});

type BridgeToken = { defuse_asset_identifier: string; origin_chain_address: string; decimals: number; asset_name: string; min_deposit_amount: string; intents_token_id: string };

export class PoaBridgeClient {
  constructor(private url = POA_BRIDGE_URL, private fetcher: typeof fetch = globalThis.fetch) {}
  private async rpc<T>(method: string, params: unknown): Promise<T> {
    let res: Response;
    try { res = await this.fetcher(this.url, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ jsonrpc: "2.0", id: 1, method, params: [params] }), signal: AbortSignal.timeout(15_000) }); }
    catch { throw new NearPublicError("intents: the PoA bridge is unreachable"); }
    const body = await res.json().catch(() => null) as { result?: T; error?: { message?: string } } | null;
    if (!res.ok || !body || body.error || body.result === undefined) throw new NearPublicError(`intents: the PoA bridge refused ${method} (${String(body?.error?.message ?? `HTTP ${res.status}`).replace(/[^\x20-\x7e]/g, "").slice(0, 160)})`);
    return body.result;
  }
  depositAddress(accountId: string, chain: string) { return this.rpc<{ address?: unknown; chain?: unknown }>("deposit_address", { account_id: accountId, chain }); }
  supportedTokens(chain: string) { return this.rpc<{ tokens?: unknown[] }>("supported_tokens", { chains: [chain] }); }
}

export class IntentsDeposits {
  constructor(private accounts: NearAccountService, private cs: ChainSignatures | null, private bridge = new PoaBridgeClient()) {}

  async depositAddress(userId: string, input: z.input<typeof intentsDepositAddressInput>) {
    const p = intentsDepositAddressInput.parse(input);
    const chain = CHAINS[p.network];
    const self = (await this.accounts.account(userId)).accountId;
    const [addr, list] = await Promise.all([this.bridge.depositAddress(self, chain), this.bridge.supportedTokens(chain)]);
    if (addr.chain !== chain || typeof addr.address !== "string" || !isAddress(addr.address, { strict: false })) throw new NearPublicError("intents: the PoA bridge returned an unexpected deposit address; do not send funds");
    const deposit = getAddress(addr.address);
    const from = this.cs ? await this.cs.fromAddress(userId) : null;
    if (from && deposit.toLowerCase() === from.toLowerCase()) throw new NearPublicError("intents: the PoA bridge returned this account's own address; do not send funds");
    const want = p.asset?.toUpperCase();
    const tokens = (Array.isArray(list.tokens) ? list.tokens : []).flatMap(t => {
      const x = t as BridgeToken;
      if (typeof x?.asset_name !== "string" || typeof x.intents_token_id !== "string" || !Number.isInteger(x.decimals) || !UINT.test(String(x.min_deposit_amount)) || typeof x.origin_chain_address !== "string") return [];
      if (!x.defuse_asset_identifier?.startsWith(`${chain}:`)) return [];
      const symbol = x.asset_name.replace(/[^\x20-\x7e]/g, "?").slice(0, 20);
      if (want && symbol.toUpperCase() !== want) return [];
      const native = x.origin_chain_address === "native";
      if (!native && !isAddress(x.origin_chain_address, { strict: false })) return [];
      return [{
        symbol, intents_asset_id: x.intents_token_id.slice(0, 200), decimals: x.decimals,
        token: native ? "native" : getAddress(x.origin_chain_address),
        min_deposit: x.min_deposit_amount, min_deposit_formatted: formatUnits(BigInt(x.min_deposit_amount), x.decimals),
        send_with: native ? `evm_call_prepare network ${p.network}, to ${deposit}, value_wei = amount, no data` : `evm_call_prepare network ${p.network}, to ${getAddress(x.origin_chain_address)}, function_name transfer, args [${deposit}, amount]`,
      }];
    });
    return {
      network: p.network, bridge: "PoA bridge (near-intents.org deposits)", credited_to: `NEAR Intents balance of ${self}`,
      deposit_address: deposit, ...(from ? { send_from: from } : {}), tokens,
      notes: [
        "The deposit address is assigned by the bridge to this NEAR account; anything of a listed token sent to it is credited to this account's intents balance, usually within a few minutes. Check with intents_balances.",
        "Amounts below min_deposit may not be credited. Send only listed tokens on this network.",
        "Keep some ETH on the sending address for gas, and about 0.05 NEAR on the NEAR account for the Chain Signatures request (mostly refunded).",
        "After it arrives, intents_trade_prepare or intents_swap_prepare (pay_from intents) can swap it, e.g. to native NEAR with deliver_to wallet.",
      ],
    };
  }
}

function formatUnits(v: bigint, decimals: number): string {
  const s = v.toString().padStart(decimals + 1, "0");
  const whole = s.slice(0, s.length - decimals), frac = s.slice(s.length - decimals).replace(/0+$/, "");
  return frac ? `${whole}.${frac}` : whole;
}
