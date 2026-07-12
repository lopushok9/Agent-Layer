import fs from "node:fs";
import path from "node:path";
import { spawnSync } from "node:child_process";

function readEnv(pathname) {
  try {
    const result = {};
    for (const line of fs.readFileSync(pathname, "utf8").split(/\r?\n/)) {
      const match = line.match(/^([A-Za-z_][A-Za-z0-9_]*)=(.*)$/);
      if (match) result[match[1]] = match[2];
    }
    return result;
  } catch (error) {
    if (error?.code === "ENOENT") return {};
    throw error;
  }
}

function readText(pathname) {
  try {
    return fs.readFileSync(pathname, "utf8");
  } catch (error) {
    if (error?.code === "ENOENT") return "";
    throw error;
  }
}

function writeSecret(pathname, value) {
  fs.mkdirSync(path.dirname(pathname), { recursive: true });
  fs.writeFileSync(pathname, `${String(value || "").trim()}\n`, { mode: 0o600 });
  try {
    fs.chmodSync(pathname, 0o600);
  } catch {
    // Best effort on filesystems without POSIX modes.
  }
}

export function createBootKeyManager({
  runtimeBase,
  openclawHome,
  currentRuntimeRoot,
  resolveVenvPython,
  expandHome,
  bridgeTimeoutMs,
  env = process.env,
}) {
  const defaultFile = path.join(runtimeBase, "boot-key");

  function currentKey() {
    const root = currentRuntimeRoot();
    if (!root) return "";
    return readEnv(path.join(root, "agent-wallet", ".env")).AGENT_WALLET_BOOT_KEY || "";
  }

  function configuredFileKey() {
    const value = String(env.AGENT_WALLET_BOOT_KEY_FILE || "").trim();
    return value ? readText(path.resolve(expandHome(value))).trim() : "";
  }

  function ensureFile() {
    const configured = String(env.AGENT_WALLET_BOOT_KEY_FILE || "").trim();
    const keyFile = configured ? path.resolve(expandHome(configured)) : defaultFile;
    if (readText(keyFile).trim()) return { path: keyFile, status: "existing" };
    const key = String(env.AGENT_WALLET_BOOT_KEY || "").trim() || configuredFileKey() || currentKey();
    if (!key) return { path: keyFile, status: "missing" };
    writeSecret(keyFile, key);
    return { path: keyFile, status: "created" };
  }

  function readKeystore() {
    const root = currentRuntimeRoot();
    if (!root) return "";
    const python = resolveVenvPython(root);
    if (!python) return "";
    try {
      const result = spawnSync(
        python,
        ["-c", "from agent_wallet.config import read_boot_key_from_keystore as r; print(r())"],
        {
          cwd: path.join(root, "agent-wallet"),
          encoding: "utf8",
          timeout: bridgeTimeoutMs,
          env: { ...env, OPENCLAW_HOME: openclawHome },
        },
      );
      return result.status === 0 ? String(result.stdout || "").trim() : "";
    } catch {
      return "";
    }
  }

  function resolveFromRuntime() {
    const root = currentRuntimeRoot();
    if (!root) return { supported: false, key: "" };
    const python = resolveVenvPython(root);
    if (!python) return { supported: false, key: "" };
    try {
      const result = spawnSync(
        python,
        ["-c", "from agent_wallet.config import resolve_boot_key_for_installer as r; print(r())"],
        {
          cwd: path.join(root, "agent-wallet"),
          encoding: "utf8",
          timeout: bridgeTimeoutMs,
          env: { ...env, OPENCLAW_HOME: openclawHome },
        },
      );
      return result.status === 0
        ? { supported: true, key: String(result.stdout || "").trim() }
        : { supported: false, key: "" };
    } catch {
      return { supported: false, key: "" };
    }
  }

  function resolveLegacy() {
    for (const [source, key] of [
      ["legacy_keystore", readKeystore()],
      ["current_runtime_env", currentKey()],
      ["configured_file", configuredFileKey()],
      ["default_file", readText(defaultFile).trim()],
    ]) {
      if (key) return { key, source };
    }
    return { key: "", source: "none" };
  }

  function provision(releaseRoot, bootKey) {
    const key = String(bootKey || "").trim();
    if (!key) return false;
    const python = resolveVenvPython(releaseRoot);
    if (!python) return false;
    try {
      const result = spawnSync(
        python,
        ["-m", "agent_wallet.openclaw_cli", "boot-key-import", "--key-stdin"],
        {
          cwd: path.join(releaseRoot, "agent-wallet"),
          input: key,
          encoding: "utf8",
          timeout: bridgeTimeoutMs,
          env: { ...env, OPENCLAW_HOME: openclawHome },
        },
      );
      return result.status === 0;
    } catch {
      return false;
    }
  }

  function verifyWithRuntime(releaseRoot) {
    const sealedPath = path.join(openclawHome, "sealed_keys.json");
    if (!fs.existsSync(sealedPath)) return { ok: true, required: false };
    const key = String(env.AGENT_WALLET_BOOT_KEY || "").trim();
    if (!key) return { ok: false, required: true, error: "no verified boot key is available" };
    const python =
      env.AGENT_WALLET_PYTHON ||
      env.OPENCLAW_AGENT_WALLET_PYTHON ||
      resolveVenvPython(releaseRoot);
    if (!python) {
      if (String(env.AGENT_WALLET_VERIFY_DISABLE || "") === "1") {
        return { ok: true, required: true, skipped: true };
      }
      return { ok: false, required: true, error: "staged Python runtime is unavailable" };
    }
    const result = spawnSync(
      python,
      [
        "-c",
        "from agent_wallet.sealed_keys import unseal_keys; import os; unseal_keys(os.environ['AGENT_WALLET_BOOT_KEY']); print('ok')",
      ],
      {
        cwd: path.join(releaseRoot, "agent-wallet"),
        encoding: "utf8",
        timeout: bridgeTimeoutMs,
        env: { ...env, OPENCLAW_HOME: openclawHome },
      },
    );
    return result.status === 0
      ? { ok: true, required: true }
      : { ok: false, required: true, error: "selected boot key does not unlock sealed wallet state" };
  }

  return { ensureFile, resolveFromRuntime, resolveLegacy, provision, verifyWithRuntime };
}
