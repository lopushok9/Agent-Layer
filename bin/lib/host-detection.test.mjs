import assert from "node:assert/strict";
import test from "node:test";
import {
  buildInstallPlan,
  detectHosts,
  stripUniversalInstallerArgs,
} from "./host-detection.mjs";

const detections = [
  { name: "openclaw", detected: false },
  { name: "codex", detected: true },
  { name: "claude-code", detected: true },
  { name: "hermes", detected: false },
];

test("fresh installs select only detected hosts", () => {
  const plan = buildInstallPlan({
    args: ["--yes"],
    detections,
    managedHosts: [],
    runtimeInstalled: false,
  });
  assert.deepEqual(plan.selected_hosts, ["codex", "claude-code"]);
  assert.equal(plan.selection_reason, "fresh_install_detected");
});

test("existing installs select managed hosts and never newly detected hosts", () => {
  const plan = buildInstallPlan({
    args: ["--yes"],
    detections,
    managedHosts: ["codex"],
    runtimeInstalled: true,
  });
  assert.deepEqual(plan.selected_hosts, ["codex"]);
  assert.equal(plan.selection_reason, "existing_runtime_managed_only");
});

test("explicit selection supports aliases and exclusions", () => {
  const plan = buildInstallPlan({
    args: ["--hosts", "all", "--exclude=claude,hermes"],
    detections,
    managedHosts: [],
    runtimeInstalled: false,
  });
  assert.deepEqual(plan.selected_hosts, ["openclaw", "codex"]);
  assert.deepEqual(plan.excluded_hosts, ["claude-code", "hermes"]);
});

test("runtime-only wins over automatic detection", () => {
  const plan = buildInstallPlan({
    args: ["--runtime-only"],
    detections,
    managedHosts: [],
    runtimeInstalled: false,
  });
  assert.deepEqual(plan.selected_hosts, []);
  assert.equal(plan.selection_reason, "runtime_only");
});

test("invalid or missing host selectors fail before installation", () => {
  assert.throws(
    () =>
      buildInstallPlan({
        args: ["--hosts", "unknown-agent"],
        detections,
        managedHosts: [],
        runtimeInstalled: false,
      }),
    /Unknown host/,
  );
  assert.throws(
    () =>
      buildInstallPlan({
        args: ["--hosts", "--yes"],
        detections,
        managedHosts: [],
        runtimeInstalled: false,
      }),
    /--hosts requires a value/,
  );
});

test("universal flags are not forwarded to the Python installer", () => {
  assert.deepEqual(
    stripUniversalInstallerArgs([
      "--yes",
      "--hosts",
      "codex",
      "--exclude=hermes",
      "--no-prompt",
      "--backend",
      "none",
    ]),
    ["--yes", "--backend", "none"],
  );
});

test("detection reports CLI and config evidence without using runtime directories", () => {
  const existing = new Set([
    "/tmp/test-home/.codex/config.toml",
    "/tmp/test-home/.claude/settings.json",
  ]);
  const hosts = detectHosts({
    env: { HOME: "/tmp/test-home" },
    commandPath: (name) => (name === "hermes" ? "/usr/bin/hermes" : ""),
    exists: (pathname) => existing.has(pathname),
  });
  const byName = Object.fromEntries(hosts.map((host) => [host.name, host]));
  assert.equal(byName.openclaw.detected, false);
  assert.equal(byName.codex.detected, true);
  assert.equal(byName["claude-code"].detected, true);
  assert.equal(byName.hermes.detected, true);
  assert.deepEqual(byName.hermes.evidence, [{ type: "cli", path: "/usr/bin/hermes" }]);
});
