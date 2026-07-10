import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import test from "node:test";

import { loadConfig } from "../src/config.js";

test("instance identity is stable per data directory", () => {
  const home = fs.mkdtempSync(path.join(os.tmpdir(), "wdk-evm-instance-"));
  try {
    const env = {
      OPENCLAW_HOME: home,
      WDK_EVM_LOCAL_TOKEN: "identity-test-token",
      WDK_EVM_NETWORK: "base",
    };
    const first = loadConfig(env);
    const second = loadConfig(env);
    assert.match(first.instanceId, /^[0-9a-f-]{32,36}$/i);
    assert.equal(second.instanceId, first.instanceId);
    assert.equal(
      fs.readFileSync(path.join(home, "wdk-evm-wallet", "instance-id"), "utf8").trim(),
      first.instanceId
    );

    const explicit = loadConfig({ ...env, WDK_EVM_INSTANCE_ID: "explicit-instance" });
    assert.equal(explicit.instanceId, "explicit-instance");
  } finally {
    fs.rmSync(home, { recursive: true, force: true });
  }
});
