import assert from "node:assert/strict";
import test from "node:test";

import { createCryptoDataConnector } from "../dist/connector.js";

function request(connector, tool, arguments_) {
  return {
    protocol_version: 1,
    request_id: `reference-${tool}`,
    connector: { id: connector.manifest.id, version: connector.manifest.version },
    tool,
    arguments: arguments_,
    context: {},
  };
}

test("normalizes public ticker data without wallet context", async () => {
  const connector = createCryptoDataConnector(async (url, options) => {
    assert.equal(url.href, "https://api.exchange.coinbase.com/products/BTC-USD/ticker");
    assert.equal(options.redirect, "error");
    assert.equal(options.headers["cache-control"], "no-cache");
    return new Response(
      JSON.stringify({
        price: "78000.12",
        bid: "78000.11",
        ask: "78000.13",
        size: "0.01",
        volume: "1234.5",
        time: "2026-08-27T00:00:00Z",
      }),
      { status: 200, headers: { "content-type": "application/json" } }
    );
  });
  const response = await connector.invoke(request(connector, "get_spot_price", {
    base: "btc",
    quote: "usd",
  }));
  assert.deepEqual(response.result, {
    product_id: "BTC-USD",
    base_currency: "BTC",
    quote_currency: "USD",
    price: "78000.12",
    bid: "78000.11",
    ask: "78000.13",
    last_size: "0.01",
    volume_24h: "1234.5",
    observed_at: "2026-08-27T00:00:00Z",
    source: "coinbase_exchange",
  });
});

test("normalizes public asset metadata", async () => {
  const connector = createCryptoDataConnector(async (url) => {
    assert.equal(url.href, "https://api.exchange.coinbase.com/currencies/BTC");
    return new Response(
      JSON.stringify({
        id: "BTC",
        name: "Bitcoin",
        min_size: "0.00000001",
        max_precision: "0.00000001",
        status: "online",
        default_network: "bitcoin",
        details: { type: "crypto" },
      }),
      { status: 200, headers: { "content-type": "application/json" } }
    );
  });
  const response = await connector.invoke(request(connector, "get_asset_metadata", { asset: "btc" }));
  assert.deepEqual(response.result, {
    asset: "BTC",
    name: "Bitcoin",
    status: "online",
    type: "crypto",
    min_size: "0.00000001",
    max_precision: "0.00000001",
    default_network: "bitcoin",
    source: "coinbase_exchange",
  });
});

test("rejects oversized and malformed upstream responses", async () => {
  const oversized = createCryptoDataConnector(async () =>
    new Response("{}", { status: 200, headers: { "content-length": "999999" } })
  );
  await assert.rejects(
    oversized.invoke(request(oversized, "get_asset_metadata", { asset: "BTC" })),
    /size limit/
  );

  const malformed = createCryptoDataConnector(async () =>
    new Response("not-json", { status: 200, headers: { "content-type": "application/json" } })
  );
  await assert.rejects(
    malformed.invoke(request(malformed, "get_asset_metadata", { asset: "BTC" })),
    /not valid JSON/
  );
});
