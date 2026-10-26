import { createHash } from "node:crypto";
import { CdpClient, type EvmSmartAccount } from "@coinbase/cdp-sdk";
import { createPublicClient, http, type Address, type Hex } from "viem";
import { base, mainnet } from "viem/chains";
import type { Config } from "./config.js";
import { chainIds, jsonValue, type NormalizedCall, type WalletNetwork } from "./transaction-builder.js";
import type { SmartWalletRecord } from "./wallet-store.js";

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
    return { status: "success", block_number: blockNumber.toString(), kind: "sequential_execution", asset_changes: jsonValue(result.assetChanges), gas_used_execution_only: result.results.reduce((n, r) => n + r.gasUsed, 0n).toString(), limitations: ["Not ERC-4337 signature/deployment validation.", "Gas is execution-only; it excludes account validation and network overhead.", "Asset changes inferred by RPC tracing can be incomplete. Simulation does not guarantee future execution."] };
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
}
