import assert from "node:assert/strict";
import test from "node:test";
import { PaymentService, selectSmartAccountRequirement } from "../src/payments.js";
const ownerAddress = "0x1111111111111111111111111111111111111111";
test("smart-wallet x402 rejects unsupported schemes and Permit2 before signing", () => {
  const requirement = { scheme: "exact", network: "eip155:8453", asset: "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913", amount: "1000", payTo: ownerAddress, maxTimeoutSeconds: 60, extra: {} };
  const challenge = (r: any) => ({ x402Version: 2, resource: { url: "https://api.example.com" }, accepts: [r] }) as any;
  assert.equal(selectSmartAccountRequirement(challenge(requirement), {} as any).scheme, "exact");
  for (const r of [{ ...requirement, scheme: "upto" }, { ...requirement, scheme: "auth-capture" }, { ...requirement, extra: { assetTransferMethod: "permit2" } }, { ...requirement, extra: { paymentFlow: "upfront" } }]) assert.throws(() => selectSmartAccountRequirement(challenge(r), {} as any), /only x402 exact/);
});

test("legacy and foreign payer previews cannot request a smart-wallet signature", async () => {
  let signatures = 0;
  const service = Object.create(PaymentService.prototype) as any;
  service.account = async () => ({ address: ownerAddress, signTypedData: async () => { signatures++; return "0x12"; } });
  for (const payerAddress of [null, "0x2222222222222222222222222222222222222222"]) {
    await assert.rejects(service.client("user", { scheme: "exact", payerAddress }, () => { signatures++; }), /different wallet version/);
  }
  assert.equal(signatures, 0);
});
