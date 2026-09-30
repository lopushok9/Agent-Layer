import assert from "node:assert/strict";
import test from "node:test";
import express from "express";
import type { AddressInfo } from "node:net";
import { authScheme, connectorDiagnostics } from "../src/diagnostics.js";

test("auth scheme classification never echoes the credential", () => {
  assert.equal(authScheme(undefined), "none");
  assert.equal(authScheme("Bearer alx402_secretvalue"), "bearer-pat");
  assert.equal(authScheme("Bearer a.b.c"), "bearer-jwt");
  assert.equal(authScheme("Bearer opaque"), "bearer-other");
  assert.equal(authScheme("alx402_secretvalue"), "raw-pat");
  assert.equal(authScheme("Basic dXNlcjpwYXNz"), "scheme:basic");
});

test("requests on any path are logged without secret or query values", async () => {
  const lines: string[] = []; const warn = console.warn; console.warn = (line: string) => { lines.push(line); };
  const app = express(); app.use(connectorDiagnostics); app.post("/mcp", (_req, res) => res.status(401).end()); app.get("/healthz", (_req, res) => res.status(500).end());
  const server = app.listen(0, "127.0.0.1"); await new Promise<void>((r) => server.once("listening", r));
  const base = `http://127.0.0.1:${(server.address() as AddressInfo).port}`;
  try {
    await fetch(`${base}/mcp`, { method: "POST", headers: { authorization: "Bearer alx402_topsecret", "x-api-key": "alx402_alsosecret", "user-agent": "Muse/1" } });
    await fetch(`${base}/?api_key=alx402_querysecret`);
    await fetch(`${base}/healthz`);
    await new Promise((r) => setTimeout(r, 50));
    assert.equal(lines.length, 2, "every path except /healthz is logged");
    const entry = JSON.parse(lines[0]!);
    assert.equal(entry.status, 401); assert.equal(entry.auth, "bearer-pat"); assert.deepEqual(entry.auth_headers, ["authorization", "x-api-key"]); assert.equal(entry.ua, "Muse/1");
    const root = JSON.parse(lines[1]!); assert.equal(root.path, "/"); assert.equal(root.status, 404); assert.deepEqual(root.query_keys, ["api_key"]);
    assert.doesNotMatch(lines.join("\n"), /topsecret|alsosecret|querysecret/);
  } finally { console.warn = warn; await new Promise<void>((r, j) => server.close((e) => (e ? j(e) : r()))); }
});
