import assert from "node:assert/strict";
import test from "node:test";
import express from "express";
import type { AddressInfo } from "node:net";
import type { Config } from "../src/config.js";
import { homeRouter } from "../src/home.js";

test("the landing page is static, locked down, and explains how to connect", async () => {
  const app = express(); app.use(homeRouter({ resource: "https://pay.example/mcp", link: null } as Config));
  app.post("/mcp", (_req, res) => { res.json({ mcp: true }); });
  const server = app.listen(0, "127.0.0.1"); await new Promise<void>((r) => server.once("listening", r));
  const base = `http://127.0.0.1:${(server.address() as AddressInfo).port}`;
  try {
    const res = await fetch(`${base}/`); const page = await res.text();
    assert.equal(res.status, 200); assert.match(res.headers.get("content-type") ?? "", /text\/html/);
    const csp = res.headers.get("content-security-policy") ?? ""; assert.match(csp, /default-src 'none'/); assert.match(csp, /frame-ancestors 'none'/);
    const nonce = csp.match(/'nonce-([^']+)'/)?.[1]; assert.ok(nonce); assert.match(page, new RegExp(`<script nonce="${nonce}">`));
    assert.match(page, /Powered by AgentLayer/); assert.match(page, /href="\/muse">Connect Muse</); assert.match(page, /Connectors/); assert.match(page, /https:\/\/pay\.example\/mcp/);
    assert.doesNotMatch(page, /Link wallet/, "Link is mentioned only when configured");
    assert.deepEqual(await (await fetch(`${base}/mcp`, { method: "POST" })).json(), { mcp: true }, "the MCP route is untouched");
  } finally { await new Promise<void>((r) => server.close(() => r())); }
});
