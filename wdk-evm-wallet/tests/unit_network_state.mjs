import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import test from "node:test";

import { EvmNetworkState } from "../src/network_state.js";

function createConfig(dataDir) {
  return {
    network: "ethereum",
    dataDir,
    networkProfiles: {
      ethereum: { chainId: 1, providerUrl: "https://eth.example", nativeSymbol: "ETH" },
      robinhood: {
        chainId: 4663,
        providerUrl: "https://robinhood.example",
        nativeSymbol: "ETH",
      },
    },
  };
}

function tempHome() {
  return fs.mkdtempSync(path.join(os.tmpdir(), "wdk-evm-network-state-"));
}

test("setActiveNetwork/getActiveNetwork round-trips robinhood", async () => {
  const home = tempHome();
  try {
    const state = new EvmNetworkState(createConfig(home));
    await state.setActiveNetwork({ network: "robinhood" });
    assert.equal(await state.getActiveNetwork(), "robinhood");
  } finally {
    fs.rmSync(home, { recursive: true, force: true });
  }
});

test("robinhood-mainnet alias normalizes when setting the active network", async () => {
  const home = tempHome();
  try {
    const state = new EvmNetworkState(createConfig(home));
    const info = await state.setActiveNetwork({ network: "robinhood-mainnet" });
    assert.equal(info.activeNetwork, "robinhood");
    assert.equal(await state.getActiveNetwork(), "robinhood");
  } finally {
    fs.rmSync(home, { recursive: true, force: true });
  }
});

test("resolveRuntimeConfig returns robinhood's chainId and nativeSymbol", async () => {
  const home = tempHome();
  try {
    const state = new EvmNetworkState(createConfig(home));
    const runtime = await state.resolveRuntimeConfig("robinhood");
    assert.equal(runtime.network, "robinhood");
    assert.equal(runtime.chainId, 4663);
    assert.equal(runtime.nativeSymbol, "ETH");
    assert.equal(runtime.providerUrl, "https://robinhood.example");
  } finally {
    fs.rmSync(home, { recursive: true, force: true });
  }
});

test("setActiveNetwork rejects an unsupported network", async () => {
  const home = tempHome();
  try {
    const state = new EvmNetworkState(createConfig(home));
    await assert.rejects(
      state.setActiveNetwork({ network: "polygon" }),
      /ethereum, sepolia, base, base-sepolia, robinhood/
    );
  } finally {
    fs.rmSync(home, { recursive: true, force: true });
  }
});
