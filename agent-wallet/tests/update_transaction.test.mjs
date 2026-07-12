import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import test from "node:test";

import { createUpdateTransactionManager } from "../../bin/lib/update-transaction.mjs";

function fixture() {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "agent-wallet-transaction-"));
  const runtimeBase = path.join(root, "agent-wallet-runtime");
  const releases = path.join(runtimeBase, "releases");
  fs.mkdirSync(releases, { recursive: true });
  const active = path.join(releases, "known-good");
  fs.mkdirSync(active);
  fs.symlinkSync(active, path.join(runtimeBase, "current"), "dir");
  const manager = createUpdateTransactionManager({
    runtimeBase,
    packageVersion: "9.9.9",
    env: {},
  });
  return { root, runtimeBase, releases, active, manager };
}

function cleanup(context) {
  fs.rmSync(context.root, { recursive: true, force: true });
}

for (const state of ["preparing", "verified"]) {
  test(`${state} staging is quarantined without changing current`, () => {
    const context = fixture();
    try {
      const staging = path.join(context.releases, `.staging-${state}`);
      const release = path.join(context.releases, "9.9.9");
      fs.mkdirSync(staging);
      context.manager.writeJournal(state, {
        staging_root: staging,
        release_root: release,
      });

      const recovery = context.manager.recover();
      assert.equal(recovery.ok, true);
      assert.equal(recovery.action, "quarantined_incomplete_staging");
      assert.equal(fs.existsSync(staging), false);
      assert.equal(fs.existsSync(recovery.quarantined_runtime), true);
      assert.equal(fs.realpathSync(path.join(context.runtimeBase, "current")), fs.realpathSync(context.active));
      assert.equal(context.manager.readJournal().state, "recovered");
    } finally {
      cleanup(context);
    }
  });
}

test("present committed release is accepted and recovery is idempotent", () => {
  const context = fixture();
  try {
    const release = path.join(context.releases, "9.9.9");
    fs.mkdirSync(release);
    context.manager.writeJournal("committing", {
      staging_root: path.join(context.releases, ".staging-missing"),
      release_root: release,
      replaced_root: path.join(context.releases, "9.9.9-replaced"),
    });

    assert.deepEqual(context.manager.recover(), {
      attempted: true,
      ok: true,
      action: "release_already_present",
    });
    assert.deepEqual(context.manager.recover(), {
      attempted: false,
      ok: true,
      reason: "no interrupted update",
    });
    assert.equal(fs.realpathSync(path.join(context.runtimeBase, "current")), fs.realpathSync(context.active));
  } finally {
    cleanup(context);
  }
});

test("journal paths outside runtime base are rejected without mutation", () => {
  const context = fixture();
  const outside = fs.mkdtempSync(path.join(os.tmpdir(), "agent-wallet-outside-"));
  try {
    context.manager.writeJournal("verified", {
      staging_root: outside,
      release_root: path.join(context.releases, "9.9.9"),
    });
    const recovery = context.manager.recover();
    assert.equal(recovery.ok, false);
    assert.match(recovery.reason, /unsafe path/);
    assert.equal(fs.existsSync(outside), true);
    assert.equal(context.manager.readJournal().state, "verified");
  } finally {
    fs.rmSync(outside, { recursive: true, force: true });
    cleanup(context);
  }
});

test("corrupt journal is diagnosed and never rewritten by recovery", () => {
  const context = fixture();
  try {
    fs.writeFileSync(context.manager.journalPath, "{not-json\n");
    const before = fs.readFileSync(context.manager.journalPath, "utf8");
    assert.equal(context.manager.status().journal_ok, false);
    const recovery = context.manager.recover();
    assert.equal(recovery.ok, false);
    assert.match(recovery.reason, /corrupt/);
    assert.equal(fs.readFileSync(context.manager.journalPath, "utf8"), before);
  } finally {
    cleanup(context);
  }
});

for (const owner of [
  { schema_version: 1, pid: 999999, hostname: "another-host", token: "foreign" },
  "{not-json\n",
]) {
  const label = typeof owner === "string" ? "unreadable" : "foreign-host";
  test(`${label} lock is not stolen`, () => {
    const context = fixture();
    try {
      fs.mkdirSync(context.manager.lockPath);
      const ownerPath = path.join(context.manager.lockPath, "owner.json");
      fs.writeFileSync(ownerPath, typeof owner === "string" ? owner : JSON.stringify(owner));
      const lock = context.manager.acquireLock();
      assert.equal(lock.ok, false);
      assert.equal(fs.existsSync(context.manager.lockPath), true);
      assert.equal(fs.readFileSync(ownerPath, "utf8"), typeof owner === "string" ? owner : JSON.stringify(owner));
    } finally {
      cleanup(context);
    }
  });
}
