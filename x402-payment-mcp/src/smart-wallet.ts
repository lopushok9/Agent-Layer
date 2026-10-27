import { createHash } from "node:crypto";
import { CdpClient, type EvmSmartAccount } from "@coinbase/cdp-sdk";
import { createPublicClient, http, type Address, type Hex } from "viem";
import { base, mainnet } from "viem/chains";
import type { Config } from "./config.js";
import { chainIds, jsonValue, type NormalizedCall, type WalletNetwork } from "./transaction-builder.js";
import type { SmartWalletRecord } from "./wallet-store.js";
import type { SwapPlan } from "./swap-plan.js";
import { validateSwapQuote } from "./managed-swaps.js";

type Registry = { wallet(userId: string): Promise<SmartWalletRecord | null>; saveWallet(userId: string, record: SmartWalletRecord): Promise<void> };
export class SmartWalletService {
  constructor(private config: Config, private registry: Registry, readonly cdp: CdpClient = new CdpClient({ apiKeyId: config.CDP_API_KEY_ID, apiKeySecret: config.CDP_API_KEY_SECRET, walletSecret: config.CDP_WALLET_SECRET })) {}
  async account(userId: string): Promise<EvmSmartAccount> {
    const existing = await this.registry.wallet(userId);
    // Separate namespace from old EOA wallets; never reinterpret legacy balances.
    const suffix = createHash("sha256").update(userId).digest("hex").slice(0, 24);
    const ownerName = existing?.ownerName ?? `owner-v2-${suffix}`;
    const accountName = existing?.accountName ?? `smart-v2-${suffix}`;
    const owner = await this.cdp.evm.getOrCreateAccount({ name: ownerName });
    const account = await this.cdp.evm.getOrCreateSmartAccount({ name: accountName, owner });
    if (account.address.toLowerCase() === owner.address.toLowerCase()) throw new Error("smart account must differ from owner EOA");
    if (existing && (existing.address.toLowerCase() !== account.address.toLowerCase() || existing.ownerAddress.toLowerCase() !== owner.address.toLowerCase())) throw new Error("smart account does not match wallet registry");
    if (!existing) await this.registry.saveWallet(userId, { ownerName, accountName, ownerAddress: owner.address, address: account.address });
    return account;
  }
  rpc(network: WalletNetwork) {
    const url = network === "base" ? this.config.BASE_RPC_URL : this.config.ETHEREUM_RPC_URL;
    if (!url) throw new Error(`${network} RPC is not configured`);
    return createPublicClient({ chain: network === "base" ? base : mainnet, transport: http(url, { timeout: 15_000, retryCount: 0 }) });
  }
  async status(userId: string, network: WalletNetwork) {
    const account = await this.account(userId);
    const rpc = this.rpc(network);
    if (await rpc.getChainId() !== chainIds[network]) throw new Error("RPC chain ID mismatch");
    const [balance, code] = await Promise.all([rpc.getBalance({ address: account.address }), rpc.getCode({ address: account.address })]);
    return { network, chain_id: chainIds[network], account_type: "cdp_smart_account", address: account.address, native_balance_wei: balance.toString(), deployed: Boolean(code && code !== "0x"), signing: "managed_cdp_owner", receive: `Fund only this smart account address on ${network}. The owner EOA is an internal signer.` };
  }
  async simulate(network: WalletNetwork, account: Address, calls: NormalizedCall[]) {
    const rpc = this.rpc(network);
    if (await rpc.getChainId() !== chainIds[network]) throw new Error("RPC chain ID mismatch");
    const blockNumber = await rpc.getBlockNumber();
    for (const call of calls) if (call.data !== "0x") {
      const code = await rpc.getCode({ address: call.to, blockNumber });
      if (!code || code === "0x") throw new Error("calldata target has no contract code on the selected network");
    }
    // eth_simulateV1 carries state between calls and preserves the smart address
    // as msg.sender. This is execution simulation, not ERC-4337 validation.
    const result = await rpc.simulateCalls({ account, calls: calls.map(c => ({ ...c, value: BigInt(c.value) })), blockNumber, traceAssetChanges: true, validation: false });
    if (result.results.some(r => r.status !== "success")) throw new Error("batch simulation reverted; nothing was signed");
    return { status: "success", block_number: blockNumber.toString(), kind: "sequential_execution", asset_changes: jsonValue(result.assetChanges), gas_used_execution_only: result.results.reduce((n, r) => n + r.gasUsed, 0n).toString(), limitations: ["Not ERC-4337 signature/deployment validation; tx.origin and deployment-time callbacks may differ.", "Gas is execution-only; it excludes account validation and network overhead.", "Asset changes inferred by RPC tracing can be incomplete. Simulation does not guarantee future execution."] };
  }
  async send(userId: string, network: WalletNetwork, calls: NormalizedCall[], id: string, beforeSigning: (hash: Hex) => Promise<void>) {
    const account = await this.account(userId);
    const owner = account.owners[0]!;
    // The pinned CDP SDK prepares once, invokes owner.sign(hash), then submits.
    // Intercept that boundary to durably save the exact hash before a signature
    // can exist. No owner address or signing tool is exposed through MCP.
    const bound = { ...account, owners: [{ ...owner, sign: async (options: Parameters<typeof owner.sign>[0]) => {
      if (!options.hash) throw new Error("CDP did not provide a UserOperation hash");
      await beforeSigning(options.hash);
      return owner.sign(options);
    } }] };
    const paymasterUrl = network === "base" ? this.config.BASE_PAYMASTER_URL : this.config.ETHEREUM_PAYMASTER_URL;
    return this.cdp.evm.sendUserOperation({ smartAccount: bound, network, calls: calls.map(c => ({ ...c, value: BigInt(c.value) })), idempotencyKey: id, ...(paymasterUrl ? { paymasterUrl } : {}) });
  }
  async operation(userId: string, userOpHash: Hex) {
    const account = await this.account(userId);
    return account.getUserOperation({ userOpHash });
  }
  async swapPrice(userId: string, p: Omit<SwapPlan, "minimumOutput">) {
    if (await this.rpc(p.network).getChainId() !== chainIds[p.network]) throw new Error("RPC chain ID mismatch");
    const account = await this.account(userId);
    if (account.address.toLowerCase() !== p.account.toLowerCase()) throw new Error("swap preview no longer matches this wallet and terms");
    return this.cdp.evm.getSwapPrice({ network: p.network, fromToken: p.fromToken, toToken: p.toToken, fromAmount: BigInt(p.fromAmount), slippageBps: p.slippageBps, taker: account.address, signerAddress: account.owners[0]!.address });
  }
  async swap(userId: string, p: SwapPlan, id: string, beforePermitSigning: (context: unknown) => Promise<void>, beforeUserOpSigning: (hash: Hex) => Promise<void>) {
    if (await this.rpc(p.network).getChainId() !== chainIds[p.network]) throw new Error("RPC chain ID mismatch");
    const account = await this.account(userId);
    if (account.address.toLowerCase() !== p.account.toLowerCase()) throw new Error("swap preview no longer matches this wallet and terms");
    const quote = await account.quoteSwap({ network: p.network, fromToken: p.fromToken, toToken: p.toToken, fromAmount: BigInt(p.fromAmount), slippageBps: p.slippageBps, idempotencyKey: swapQuoteKey(id) });
    if (!quote.liquidityAvailable) throw new Error("no swap liquidity is available for these tokens and amount");
    const owner = account.owners[0]!;
    validateSwapQuote(p, quote, owner.address);
    // CDP signs Permit2 directly via its API, before owner.sign(UserOp hash).
    // Persist the quote boundary first: a failure without a userOp hash can
    // still follow a Permit2 signature and must never be called "not signed".
    await beforePermitSigning(jsonValue({ ...quote, execute: undefined }));
    // swap() closes over the original account, so a shallow account copy would
    // not intercept UserOp signing. This request-local account is not cached.
    account.owners[0] = { ...owner, sign: async options => {
      if (!options.hash) throw new Error("CDP did not provide a UserOperation hash");
      await beforeUserOpSigning(options.hash);
      return owner.sign(options);
    } };
    try {
      const paymasterUrl = p.network === "base" ? this.config.BASE_PAYMASTER_URL : this.config.ETHEREUM_PAYMASTER_URL;
      return await account.swap({ swapQuote: quote, idempotencyKey: id, ...(paymasterUrl ? { paymasterUrl } : {}) });
    } finally { account.owners[0] = owner; }
  }
}

// CDP idempotency keys must not be reused across quote and submission endpoints.
function swapQuoteKey(id: string): string {
  const bytes = createHash("sha256").update(`managed-swap-quote:${id}`).digest().subarray(0, 16);
  bytes[6] = (bytes[6]! & 0x0f) | 0x40;
  bytes[8] = (bytes[8]! & 0x3f) | 0x80;
  const hex = bytes.toString("hex");
  return `${hex.slice(0,8)}-${hex.slice(8,12)}-${hex.slice(12,16)}-${hex.slice(16,20)}-${hex.slice(20)}`;
}
