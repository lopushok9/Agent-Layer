import assert from "node:assert/strict";
import { randomUUID } from "node:crypto";
import test from "node:test";
import { Store } from "../src/store.js";
import { WalletStore } from "../src/wallet-store.js";
import { transactionFingerprint } from "../src/transaction-builder.js";
import { TransactionService } from "../src/transactions.js";

test("Postgres: JSONB key order and balance drift do not invalidate a simulation; changed assets and worse deltas still block signing", { skip: !process.env.TEST_DATABASE_URL }, async () => {
  const store = new Store(process.env.TEST_DATABASE_URL!);
  try {
    await store.migrate();
    const operations = new WalletStore(store.pool);
    const user = await store.upsertIdentity("github", `simulation-order-${randomUUID()}`, null, null);
    const address = "0x1111111111111111111111111111111111111111";
    const target = "0x2222222222222222222222222222222222222222";
    const hash = `0x${"a".repeat(64)}` as const;
    const calls = [{ to: target, value: "0", data: "0x" }] as const;
    const original = [{ token: { address: target, decimals: 6, symbol: "USDC" }, value: { pre: "1000000", post: "1000000", diff: "0" } }];
    for (const change of ["none", "pre", "post", "token", "diff"] as const) {
      const preview = await operations.createOperation({ userId: user, network: "base", address, calls: [...calls], descriptions: [], fingerprint: transactionFingerprint("base", address, [...calls]), simulation: { asset_changes: original } }, 600);
      assert.deepEqual(preview.simulation.asset_changes, original);
      assert.notEqual(JSON.stringify(preview.simulation.asset_changes), JSON.stringify(original), "exercise real JSONB object-key reordering");
      const fresh = structuredClone(original);
      if (change === "token") fresh[0]!.token.address = address;
      else if (change === "diff") fresh[0]!.value.diff = "-1";
      else if (change !== "none") fresh[0]!.value[change] = "999999";
      let signatures = 0;
      const wallets = {
        account: async () => ({ address }),
        simulate: async () => ({ asset_changes: fresh }),
        send: async (_user: unknown, _network: unknown, _calls: unknown, _id: unknown, before: (incomingHash: typeof hash) => Promise<void>) => {
          await before(hash); signatures++; return { userOpHash: hash };
        },
      };
      const service = new TransactionService(wallets as any, operations, store, 600);
      if (change === "none" || change === "pre" || change === "post") {
        assert.equal((await service.execute(user, preview.id, "unchanged persisted preview")).status, "submitted");
        assert.equal(signatures, 1);
        await operations.finish(preview.id, "confirmed", hash);
      } else {
        await assert.rejects(service.execute(user, preview.id, "changed simulation"), /differ from preview/);
        assert.equal(signatures, 0, `${change} changed before signing`);
        const stopped = await operations.operation(user, preview.id);
        assert.equal(stopped!.status, "failed");
        assert.equal(stopped!.userOpHash, null);
      }
    }
  } finally { await store.close(); }
});

test("Postgres: previews expire, are single-use and isolate users; pending operations block concurrent execution", { skip: !process.env.TEST_DATABASE_URL }, async () => {
  const store = new Store(process.env.TEST_DATABASE_URL!);
  try {
    await store.migrate(); await store.migrate();
    const wallets = new WalletStore(store.pool);
    const alice = await store.upsertIdentity("github", `smart-a-${randomUUID()}`, null, null);
    const bob = await store.upsertIdentity("github", `smart-b-${randomUUID()}`, null, null);
    const address = `0x${randomUUID().replaceAll("-", "").slice(0, 32)}12345678` as const;
    const owner = `0x${randomUUID().replaceAll("-", "").slice(0, 32)}87654321` as const;
    const registry = { ownerName: `owner-${randomUUID()}`, ownerAddress: owner, accountName: `smart-${randomUUID()}`, address };
    await wallets.saveWallet(alice, registry); await wallets.saveWallet(alice, registry);
    assert.equal((await wallets.wallet(alice))!.address, address);
    assert.equal(await wallets.wallet(bob), null);
    await assert.rejects(wallets.saveWallet(alice, { ...registry, address: owner }), /mismatch/);
    const calls = [{ to: owner, value: "0", data: "0x" }] as const;
    const create = (network: "base" | "ethereum" = "base", ttl = 600) => wallets.createOperation({ userId: alice, network, address, calls: [...calls], descriptions: [], fingerprint: transactionFingerprint(network, address, [...calls]), simulation: { asset_changes: [] } }, ttl);
    const a = await create(); const b = await create();
    assert.equal(await wallets.operation(bob, a.id), null);
    await assert.rejects(wallets.reserve(bob, a.id, "foreign"), /not found/);
    const attempts = await Promise.allSettled([wallets.reserve(alice, a.id, "first"), wallets.reserve(alice, b.id, "second")]);
    assert.equal(attempts.filter(r => r.status === "fulfilled").length, 1);
    const winner = (attempts.find(r => r.status === "fulfilled") as PromiseFulfilledResult<any>).value;
    const hash = `0x${"a".repeat(64)}` as const;
    await wallets.beforeSigning(winner.id, hash);
    assert.equal((await wallets.operation(alice, winner.id))!.userOpHash, hash);
    await assert.rejects(wallets.beforeSigning(winner.id, hash), /no longer available/);
    await wallets.finish(winner.id, "unknown");
    const c = await create();
    await assert.rejects(wallets.reserve(alice, c.id, "retry"), /unresolved/);
    const otherNetwork = await create("ethereum");
    assert.equal((await wallets.reserve(alice, otherNetwork.id, "other network")).network, "ethereum");
    await wallets.finish(winner.id, "confirmed", hash);
    await assert.rejects(wallets.reserve(alice, winner.id, "replay"), /consumed/);
    const expired = await create("base", -1);
    await assert.rejects(wallets.reserve(alice, expired.id, "expired"), /expired/);
    assert.equal((await wallets.operation(alice, expired.id))!.status, "prepared", "failed reservation rolls back");
    const beforeSignExpiry = await create();
    await wallets.reserve(alice, beforeSignExpiry.id, "test signing expiry");
    await store.pool.query("UPDATE wallet_operations SET expires_at=now()-interval '1 second' WHERE id=$1", [beforeSignExpiry.id]);
    await assert.rejects(wallets.beforeSigning(beforeSignExpiry.id, hash), /no longer available/);
    const payment = await store.createPreview({ userId: alice, payerAddress: address, method: "GET", url: "https://api.example.com", headers: null, body: null, textBody: null, paymentRequired: "challenge", fingerprint: "test", scheme: "exact", amount: "1", payTo: owner }, 600);
    assert.equal((await store.reservePayment(alice, payment.id, null, "test")).preview.payerAddress, address, "x402 preview keeps its original payer");
    const swapPlan = { network: "base" as const, account: address, fromToken: owner, toToken: address, fromAmount: "10", minimumOutput: "9", slippageBps: 100 };
    const swap = await wallets.createOperation({ userId: bob, network: "base", address, kind: "swap", swapPlan, calls: [], descriptions: [], fingerprint: "swap-test", simulation: {} }, 300);
    await assert.rejects(wallets.reserve(bob, swap.id, "wrong tool"), /operation type/);
    assert.equal((await wallets.operation(bob, swap.id))!.status, "prepared");
    await wallets.reserve(bob, swap.id, "managed swap", "swap");
    const conflicting = await wallets.createOperation({ userId: bob, network: "base", address, calls: [...calls], descriptions: [], fingerprint: "calls-test", simulation: {} }, 600);
    await assert.rejects(wallets.reserve(bob, conflicting.id, "conflict"), /unresolved/);
    await wallets.beforeSwapSigning(swap.id, { quote: "validated", amount: "10" });
    assert.equal((await wallets.operation(bob, swap.id))!.userOpHash, null, "Permit2 signing boundary precedes UserOp hash");
    assert.deepEqual((await store.pool.query("SELECT execution_context FROM wallet_operations WHERE id=$1", [swap.id])).rows[0].execution_context, { quote: "validated", amount: "10" });
    await wallets.beforeSigning(swap.id, hash);
    assert.equal((await wallets.operation(bob, swap.id))!.userOpHash, hash);
    await wallets.finish(swap.id, "unknown");
    await assert.rejects(wallets.reserve(bob, conflicting.id, "retry"), /unresolved/);
  } finally { await store.close(); }
});
