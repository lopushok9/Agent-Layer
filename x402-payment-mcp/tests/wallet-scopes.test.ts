import assert from "node:assert/strict";
import test from "node:test";
import express from "express";
import { oauthRouter } from "../src/oauth.js";
import { pkceChallenge } from "../src/security.js";

test("OAuth preserves explicitly requested wallet scope and never adds it to default grants", async () => {
  const states: any[] = [];
  const client = { clientId: "client", clientName: "Tester", redirectUris: ["https://client.example/callback"] };
  const store = { consumeRateLimit: async () => true, getClient: async () => client, createLoginState: async (s: any) => { states.push(s); return "state"; } };
  const app = express(); app.use(express.json());
  app.use(oauthRouter({ issuer: "https://pay.example", resource: "https://pay.example/mcp", GITHUB_CLIENT_ID: "id", GITHUB_CLIENT_SECRET: "secret" } as any, store as any, {} as any));
  const server = app.listen(0, "127.0.0.1");
  await new Promise<void>(resolve => server.once("listening", resolve));
  const base = `http://127.0.0.1:${(server.address() as any).port}`;
  const query = (scope?: string) => new URLSearchParams({ client_id: "client", redirect_uri: client.redirectUris[0]!, response_type: "code", state: "client-state", resource: "https://pay.example/mcp", code_challenge: pkceChallenge("verifier"), code_challenge_method: "S256", ...(scope ? { scope } : {}) });
  try {
    assert.equal((await fetch(`${base}/oauth/authorize?${query()}`)).status, 200);
    assert.equal(states[0].scope, "x402:pay");
    assert.equal((await fetch(`${base}/oauth/authorize?${query("x402:pay wallet:transact")}`)).status, 200);
    assert.equal(states[1].scope, "x402:pay wallet:transact");
    assert.equal((await fetch(`${base}/oauth/authorize?${query("wallet:admin")}`)).status, 400);
    assert.equal(states.length, 2);
  } finally { await new Promise<void>((resolve, reject) => server.close(e => e ? reject(e) : resolve())); }
});
