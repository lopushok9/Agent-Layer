import { NameRegistration, nameRegisterInput } from "../name-registration.js";
import { NearPublicError } from "./operations.js";
import type { ChainSignatures } from "./chain-signatures.js";

export { nameRegisterInput as nearNameRegisterInput };

// Bind ownership and every preview to the NEAR-derived EOA, not the CDP wallet.
export class NearNameRegistration {
  private registration: NameRegistration;
  constructor(chain: Pick<ChainSignatures, "fromAddress" | "rpcFor" | "prepare">) {
    this.registration = new NameRegistration(
      { account: async userId => ({ address: await chain.fromAddress(userId) }), rpc: network => chain.rpcFor(network) },
      async (userId, input) => {
        const call = input.calls[0];
        if (input.network !== "base" || input.calls.length !== 1 || !call) throw new Error("unexpected registration call");
        return chain.prepare(userId, { network: "base", to: call.to, value_wei: call.value, data: call.data });
      },
    );
  }

  async prepare(userId: string, input: Parameters<NameRegistration["register"]>[1]) {
    try { return await this.registration.register(userId, input); }
    catch (error) {
      if (error instanceof Error && /^(not a valid ENS name|ENS \.eth registration and renewal are not supported|a Basename is one label|this name is not valid for registration|this name is already registered)/.test(error.message)) throw new NearPublicError(error.message);
      throw error;
    }
  }
}
