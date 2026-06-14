import assert from "node:assert/strict";
import test from "node:test";

import { WdkEvmWalletService } from "../src/wdk_evm_wallet.js";

const DEFAULT_ADDRESS = "0x1111111111111111111111111111111111111111";
const DEFAULT_MARKET_ID =
  "0x9103c3b4e834476c9a62ea009ba2c884ee42e94e6e314a26f04d312434191836";
const DEFAULT_VAULT_ADDRESS = "0xb576765fB15505433aF24FEe2c0325895C559FB2";

function createService() {
  return new WdkEvmWalletService({
    network: "base",
    morphoApiBaseUrl: "https://morpho-api.test/graphql",
    networkProfiles: {
      ethereum: {
        chainId: 1,
        providerUrl: "http://fake-rpc.local",
        nativeSymbol: "ETH",
      },
      base: {
        chainId: 8453,
        providerUrl: "http://fake-rpc.local",
        nativeSymbol: "ETH",
      },
    },
  });
}

function withMockedFetch(handler, callback) {
  const original = globalThis.fetch;
  globalThis.fetch = handler;
  return Promise.resolve()
    .then(callback)
    .finally(() => {
      globalThis.fetch = original;
    });
}

test("morpho vault list returns discovery payload", async () => {
  const service = createService();
  const calls = [];

  await withMockedFetch(async (_url, options) => {
    const body = JSON.parse(String(options?.body || "{}"));
    calls.push(body);
    return {
      ok: true,
      status: 200,
      async json() {
        return {
          data: {
            vaultV2s: {
              items: [
                {
                  address: DEFAULT_VAULT_ADDRESS,
                  symbol: "pyUSDm",
                  name: "Paypal USD Main",
                  listed: true,
                  asset: {
                    address: "0x0000000000000000000000000000000000000002",
                    symbol: "PYUSD",
                    decimals: 6,
                    name: "PayPal USD",
                    priceUsd: 1,
                    yield: { apr: 0, lookback: 86400 },
                  },
                  chain: { id: 8453, network: "base" },
                },
              ],
            },
          },
        };
      },
    };
  }, async () => {
    const result = await service.getMorphoVaults({ network: "base" });
    assert.equal(result.protocol, "morpho");
    assert.equal(result.vaultCount, 1);
    assert.equal(result.vaults[0].address, DEFAULT_VAULT_ADDRESS);
    assert.equal(result.listedOnly, true);
  });

  assert.equal(calls.length, 1);
  assert.equal(calls[0].operationName, "MorphoVaultV2List");
  assert.deepEqual(calls[0].variables.where, { chainId_in: [8453], listed: true });
});

test("morpho market by id returns detailed payload", async () => {
  const service = createService();

  await withMockedFetch(async (_url, options) => {
    const body = JSON.parse(String(options?.body || "{}"));
    assert.equal(body.operationName, "MorphoMarketById");
    assert.equal(body.variables.marketId, DEFAULT_MARKET_ID);
    return {
      ok: true,
      status: 200,
      async json() {
        return {
          data: {
            marketById: {
              marketId: DEFAULT_MARKET_ID,
              lltv: "860000000000000000",
              loanAsset: { address: "0xloan", symbol: "USDC", decimals: 6, name: "USD Coin" },
              collateralAsset: {
                address: "0xcollateral",
                symbol: "cbBTC",
                decimals: 8,
                name: "Coinbase Wrapped BTC",
              },
              supplyingVaultV2s: [
                { address: "0xvault1", name: "Steakhouse USDC", symbol: "steakUSDC" },
              ],
            },
          },
        };
      },
    };
  }, async () => {
    const result = await service.getMorphoMarkets({
      network: "base",
      marketId: DEFAULT_MARKET_ID,
    });
    assert.equal(result.protocol, "morpho");
    assert.equal(result.found, true);
    assert.equal(result.market.marketId, DEFAULT_MARKET_ID);
    assert.equal(result.market.supplyingVaultV2s.length, 1);
  });
});

test("morpho positions returns user overview from explicit address", async () => {
  const service = createService();

  await withMockedFetch(async (_url, options) => {
    const body = JSON.parse(String(options?.body || "{}"));
    assert.equal(body.operationName, "MorphoUserByAddress");
    assert.equal(body.variables.address, DEFAULT_ADDRESS);
    return {
      ok: true,
      status: 200,
      async json() {
        return {
          data: {
            userByAddress: {
              address: DEFAULT_ADDRESS,
              marketPositions: [
                {
                  market: {
                    marketId: DEFAULT_MARKET_ID,
                    loanAsset: { address: "0xloan", symbol: "USDC", decimals: 6, name: "USD Coin" },
                    collateralAsset: {
                      address: "0xcollateral",
                      symbol: "cbBTC",
                      decimals: 8,
                      name: "Coinbase Wrapped BTC",
                    },
                  },
                  state: {
                    supplyShares: "10",
                    supplyAssets: "1000000",
                    supplyAssetsUsd: 1,
                    borrowShares: "0",
                    borrowAssets: "0",
                    borrowAssetsUsd: 0,
                    collateral: "0",
                    collateralUsd: 0,
                  },
                },
              ],
              vaultV2Positions: [
                {
                  vault: {
                    address: DEFAULT_VAULT_ADDRESS,
                    name: "Paypal USD Main",
                    symbol: "pyUSDm",
                    asset: {
                      address: "0xasset",
                      symbol: "PYUSD",
                      decimals: 6,
                      name: "PayPal USD",
                    },
                  },
                  shares: "5",
                  assets: "5000000",
                  assetsUsd: 5,
                },
              ],
            },
          },
        };
      },
    };
  }, async () => {
    const result = await service.getMorphoPositions({
      network: "base",
      address: DEFAULT_ADDRESS,
    });
    assert.equal(result.protocol, "morpho");
    assert.equal(result.marketPositionCount, 1);
    assert.equal(result.vaultPositionCount, 1);
    assert.equal(result.address, DEFAULT_ADDRESS);
  });
});

test("morpho api graphql errors are shaped", async () => {
  const service = createService();

  await withMockedFetch(async () => ({
    ok: true,
    status: 200,
    async json() {
      return {
        errors: [{ message: "bad query" }],
      };
    },
  }), async () => {
    await assert.rejects(
      () => service.getMorphoVaults({ network: "base" }),
      (error) => error?.errorCode === "morpho_api_failed" && /bad query/.test(error.message)
    );
  });
});
