import assert from "node:assert/strict";
import test from "node:test";

import { connector } from "../dist/connector.js";

test("normalizes upstream data into the declared output schema", async () => {
  const previousFetch = globalThis.fetch;
  const previousUrl = process.env.UPSTREAM_API_URL;
  process.env.UPSTREAM_API_URL = "https://api.example.com";
  globalThis.fetch = async (url, options) => {
    assert.equal(url.hostname, "api.example.com");
    assert.equal(url.searchParams.get("chain"), "base");
    assert.equal(options.redirect, "error");
    return new Response(
      JSON.stringify({
        pools: [
          { id: "pool-1", symbol: "USDC", apy: 5.2, tvl_usd: 1000000, ignored: true },
          { id: 123, symbol: "invalid" },
        ],
      }),
      { status: 200, headers: { "content-type": "application/json" } }
    );
  };
  try {
    const result = await connector.invoke({
      protocol_version: 1,
      request_id: "template-request-1",
      connector: { id: connector.manifest.id, version: connector.manifest.version },
      tool: "get_pools",
      arguments: { chain: "base", limit: 10 },
      context: { chain: "evm", network: "base" },
    });
    assert.deepEqual(result.result, {
      pools: [{ id: "pool-1", symbol: "USDC", apy: 5.2, tvl_usd: 1000000 }],
    });
  } finally {
    globalThis.fetch = previousFetch;
    if (previousUrl === undefined) delete process.env.UPSTREAM_API_URL;
    else process.env.UPSTREAM_API_URL = previousUrl;
  }
});

test("rejects an upstream host outside the manifest allowlist", async () => {
  const previousUrl = process.env.UPSTREAM_API_URL;
  process.env.UPSTREAM_API_URL = "https://attacker.example";
  try {
    await assert.rejects(
      connector.invoke({
        protocol_version: 1,
        request_id: "template-request-2",
        connector: { id: connector.manifest.id, version: connector.manifest.version },
        tool: "get_pools",
        arguments: { chain: "base" },
        context: {},
      }),
      /permissions\.network_hosts/
    );
  } finally {
    if (previousUrl === undefined) delete process.env.UPSTREAM_API_URL;
    else process.env.UPSTREAM_API_URL = previousUrl;
  }
});
