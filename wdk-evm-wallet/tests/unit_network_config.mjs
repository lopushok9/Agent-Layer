import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import test from "node:test";

import { loadConfig } from "../src/config.js";

function tempHome() {
  return fs.mkdtempSync(path.join(os.tmpdir(), "wdk-evm-robinhood-config-"));
}

test("robinhood mainnet profile has the expected defaults", () => {
  const home = tempHome();
  try {
    const config = loadConfig({ OPENCLAW_HOME: home });
    assert.deepEqual(config.networkProfiles.robinhood, {
      chainId: 4663,
      nativeSymbol: "ETH",
      providerUrl:
        "https://agent-layer-production.up.railway.app/v1/evm/rpc/robinhood?provider=alchemy",
    });
    assert.deepEqual(config.uniswapRouterVersionsByNetwork, { robinhood: "2.1.1" });
  } finally {
    fs.rmSync(home, { recursive: true, force: true });
  }
});

test("WDK_EVM_NETWORK=robinhood is accepted as the active network", () => {
  const home = tempHome();
  try {
    const config = loadConfig({ OPENCLAW_HOME: home, WDK_EVM_NETWORK: "robinhood" });
    assert.equal(config.network, "robinhood");
  } finally {
    fs.rmSync(home, { recursive: true, force: true });
  }
});

test("robinhood-mainnet alias normalizes to robinhood", () => {
  const home = tempHome();
  try {
    const config = loadConfig({ OPENCLAW_HOME: home, WDK_EVM_NETWORK: "robinhood-mainnet" });
    assert.equal(config.network, "robinhood");
  } finally {
    fs.rmSync(home, { recursive: true, force: true });
  }
});

test("per-network Uniswap router versions are parsed and normalized", () => {
  const home = tempHome();
  try {
    const config = loadConfig({
      OPENCLAW_HOME: home,
      UNISWAP_ROUTER_VERSION_BY_NETWORK: '{"base-mainnet":"2.0","robinhood":"2.0"}',
    });
    assert.deepEqual(config.uniswapRouterVersionsByNetwork, { base: "2.0", robinhood: "2.0" });
  } finally {
    fs.rmSync(home, { recursive: true, force: true });
  }
});

test("invalid WDK_EVM_NETWORK error message lists robinhood", () => {
  const home = tempHome();
  try {
    assert.throws(
      () => loadConfig({ OPENCLAW_HOME: home, WDK_EVM_NETWORK: "polygon" }),
      /ethereum, sepolia, base, base-sepolia, robinhood/
    );
  } finally {
    fs.rmSync(home, { recursive: true, force: true });
  }
});
