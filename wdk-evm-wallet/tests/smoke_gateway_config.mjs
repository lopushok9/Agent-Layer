import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import test from "node:test";

import { loadConfig } from "../src/config.js";

test("ethereum and base mainnet profiles are always forced through provider-gateway alchemy", () => {
  const tempHome = fs.mkdtempSync(path.join(os.tmpdir(), "wdk-evm-config-"));
  try {
    const config = loadConfig({
      OPENCLAW_HOME: tempHome,
      WDK_EVM_RPC_PROVIDER_MODE: "public",
      WDK_EVM_RPC_GATEWAY_PROVIDER: "shared",
      PROVIDER_GATEWAY_URL: "https://gateway.example",
      PROVIDER_GATEWAY_BEARER_TOKEN: "gateway-secret",
      WDK_EVM_ETHEREUM_RPC_URL: "https://direct-eth.example",
      WDK_EVM_BASE_RPC_URL: "https://direct-base.example",
      WDK_EVM_SEPOLIA_RPC_URL: "https://direct-sepolia.example",
      WDK_EVM_BASE_SEPOLIA_RPC_URL: "https://direct-base-sepolia.example",
    });

    assert.equal(
      config.networkProfiles.ethereum.providerUrl,
      "https://gateway.example/v1/evm/rpc/ethereum?provider=alchemy&token=gateway-secret"
    );
    assert.equal(
      config.networkProfiles.base.providerUrl,
      "https://gateway.example/v1/evm/rpc/base?provider=alchemy&token=gateway-secret"
    );
    assert.equal(config.networkProfiles.sepolia.providerUrl, "https://direct-sepolia.example");
    assert.equal(
      config.networkProfiles["base-sepolia"].providerUrl,
      "https://direct-base-sepolia.example"
    );
  } finally {
    fs.rmSync(tempHome, { recursive: true, force: true });
  }
});
