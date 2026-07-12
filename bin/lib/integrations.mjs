import fs from "node:fs";
import path from "node:path";
import { spawnSync } from "node:child_process";

function readJson(pathname) {
  try {
    return JSON.parse(fs.readFileSync(pathname, "utf8"));
  } catch (error) {
    if (error?.code === "ENOENT") return null;
    throw error;
  }
}

function writeJsonAtomic(pathname, value) {
  fs.mkdirSync(path.dirname(pathname), { recursive: true });
  const temporary = `${pathname}.tmp-${process.pid}-${Date.now()}`;
  try {
    fs.writeFileSync(temporary, `${JSON.stringify(value, null, 2)}\n`, { mode: 0o600 });
    fs.renameSync(temporary, pathname);
    fs.chmodSync(pathname, 0o600);
  } finally {
    fs.rmSync(temporary, { force: true });
  }
}

export function createIntegrationManager({ runtimeBase, packageVersion, activeVersion }) {
  const registryPath = path.join(runtimeBase, "integrations.json");

  function emptyRegistry(error = "") {
    return {
      schema_version: 1,
      integrations: {},
      ...(error ? { registry_error: error } : {}),
    };
  }

  function readRegistry() {
    let payload;
    try {
      payload = readJson(registryPath);
    } catch (error) {
      return emptyRegistry(`integration registry is unreadable: ${error.message}`);
    }
    if (!payload) return emptyRegistry();
    if (
      payload.schema_version !== 1 ||
      !payload.integrations ||
      typeof payload.integrations !== "object" ||
      Array.isArray(payload.integrations)
    ) {
      return emptyRegistry("integration registry schema is invalid");
    }
    return payload;
  }

  function quarantineCorruptRegistry(registry) {
    if (!registry.registry_error || !fs.existsSync(registryPath)) return null;
    let backup = `${registryPath}.corrupt-${Date.now()}`;
    let suffix = 2;
    while (fs.existsSync(backup)) {
      backup = `${registryPath}.corrupt-${Date.now()}-${suffix}`;
      suffix += 1;
    }
    fs.renameSync(registryPath, backup);
    return backup;
  }

  function record(name, details = {}) {
    let registry = readRegistry();
    const corruptBackup = quarantineCorruptRegistry(registry);
    if (registry.registry_error) registry = emptyRegistry();
    if (corruptBackup) registry.recovered_corrupt_registry = path.basename(corruptBackup);
    registry.integrations[name] = {
      ...details,
      managed: true,
      installed_version: packageVersion,
      updated_at: new Date().toISOString(),
    };
    registry.updated_at = new Date().toISOString();
    writeJsonAtomic(registryPath, registry);
    return registry.integrations[name];
  }

  function managed(name) {
    const entry = readRegistry().integrations[name];
    return entry?.managed === true ? entry : null;
  }

  function status() {
    const active = activeVersion();
    const registry = readRegistry();
    const managedIntegrations = Object.entries(registry.integrations)
      .filter(([, entry]) => entry?.managed === true)
      .sort(([left], [right]) => left.localeCompare(right))
      .map(([name, entry]) => {
        const versionInSync = active === null || entry.installed_version === active;
        const registrationOk = entry.registration_ok !== false;
        return {
          name,
          installed_version: entry.installed_version || null,
          active_version: active,
          in_sync: versionInSync && registrationOk,
          registration_ok: registrationOk,
          restart_required: Boolean(entry.restart_required),
        };
      });
    return {
      in_sync: !registry.registry_error && managedIntegrations.every((entry) => entry.in_sync),
      registry_ok: !registry.registry_error,
      registry_error: registry.registry_error || "",
      recovered_corrupt_registry: registry.recovered_corrupt_registry || null,
      integrations: managedIntegrations,
    };
  }

  function safelyRefresh(name, callback) {
    try {
      return callback();
    } catch (error) {
      const fix = name === "global-cli"
        ? "Re-run: wallet update --yes"
        : name === "openclaw"
          ? "Re-run: wallet install --yes"
          : `Re-run: wallet ${name} install --yes`;
      return {
        name,
        attempted: true,
        ok: false,
        repaired: false,
        error: error?.message || String(error),
        restart_required: false,
        fix,
      };
    }
  }

  function refreshAll(refreshers) {
    return Object.entries(refreshers)
      .map(([name, callback]) => safelyRefresh(name, callback))
      .filter(Boolean);
  }

  return { registryPath, readRegistry, record, managed, status, safelyRefresh, refreshAll };
}

export function createHostIntegrationManager({
  env,
  packageRoot,
  registry,
  currentRuntimePath,
  openclawHome,
  hermesHome,
  codexHome,
  codexPluginRoot,
  codexMarketplacePath,
  claudeMarketplaceDir,
  claudeMarketplaceName,
  expandHome,
  resolveVenvPython,
  commandPath,
  repairRuntimeSymlink,
  repairHermesEnv,
  ensureCodexMarketplaceEntry,
  ensureClaudeCodeMarketplace,
  pinClaudeCacheCopies,
}) {
  const runtimeBase = path.dirname(currentRuntimePath);

  function runtimeOwnedTarget(target) {
    const relative = path.relative(runtimeBase, path.resolve(target));
    return relative === "" || (!relative.startsWith(`..${path.sep}`) && !path.isAbsolute(relative));
  }

  function symlinkTarget(linkPath) {
    try {
      if (!fs.lstatSync(linkPath).isSymbolicLink()) return null;
      return path.resolve(path.dirname(linkPath), fs.readlinkSync(linkPath));
    } catch {
      return null;
    }
  }

  function symlinkManifestMatches(linkPath, manifestRelativePath, expectedName) {
    try {
      const target = symlinkTarget(linkPath);
      if (!target || !runtimeOwnedTarget(target)) return false;
      return readJson(path.join(target, manifestRelativePath))?.name === expectedName;
    } catch {
      return false;
    }
  }

  function adoptHermes() {
    const pluginTarget = path.join(hermesHome, "plugins", "agent_wallet");
    const target = symlinkTarget(pluginTarget);
    if (!target || !runtimeOwnedTarget(target)) return null;
    let manifest = "";
    try {
      manifest = fs.readFileSync(path.join(target, "plugin.yaml"), "utf8");
    } catch {
      return null;
    }
    if (!/^name:\s*agent[-_]wallet\s*$/m.test(manifest)) return null;
    return registry.record("hermes", {
      hermes_home: hermesHome,
      plugin_target: pluginTarget,
      env_path: path.join(hermesHome, ".env"),
      adopted_legacy_install: true,
    });
  }

  function adoptCodex() {
    let marketplace;
    try {
      marketplace = readJson(codexMarketplacePath);
    } catch {
      return null;
    }
    const pluginTarget = path.join(codexPluginRoot, "agent-wallet");
    const registered = Array.isArray(marketplace?.plugins) && marketplace.plugins.some(
      (item) => item?.name === "agent-wallet" && item?.source?.source === "local",
    );
    if (!registered || !symlinkManifestMatches(pluginTarget, ".codex-plugin/plugin.json", "agent-wallet")) {
      return null;
    }
    return registry.record("codex", {
      codex_home: codexHome,
      plugin_target: pluginTarget,
      marketplace_path: codexMarketplacePath,
      marketplace_name: String(marketplace.name || "local"),
      adopted_legacy_install: true,
    });
  }

  function adoptClaudeCode() {
    let manifest;
    try {
      manifest = readJson(path.join(claudeMarketplaceDir, ".claude-plugin", "marketplace.json"));
    } catch {
      return null;
    }
    const pluginTarget = path.join(claudeMarketplaceDir, "plugins", "agent-wallet");
    const registered = manifest?.name === claudeMarketplaceName &&
      Array.isArray(manifest.plugins) && manifest.plugins.some((item) => item?.name === "agent-wallet");
    if (!registered || !symlinkManifestMatches(pluginTarget, ".claude-plugin/plugin.json", "agent-wallet")) {
      return null;
    }
    return registry.record("claude-code", {
      marketplace_dir: claudeMarketplaceDir,
      plugin_target: pluginTarget,
      cache_root: path.resolve(expandHome(env.AGENT_WALLET_CLAUDE_CODE_CACHE_ROOT || "~/.claude/plugins/cache")),
      adopted_legacy_install: true,
    });
  }

  function runHostRefresh(command, args, commandEnv = env) {
    const binary = commandPath(command);
    if (!binary) {
      return { attempted: false, ok: false, error: `${command} CLI not found`, fix: args.join(" ") };
    }
    const result = spawnSync(binary, args, { cwd: packageRoot, encoding: "utf8", env: commandEnv });
    return {
      attempted: true,
      ok: result.status === 0,
      error: result.status === 0 ? "" : (result.stderr || result.stdout || "").trim(),
      fix: result.status === 0 ? "" : `${command} ${args.join(" ")}`,
    };
  }

  function refreshOpenclaw() {
    const entry = registry.managed("openclaw");
    if (!entry) {
      return { name: "openclaw", attempted: false, ok: true, repaired: false, reason: "not managed" };
    }
    const configPath = path.resolve(expandHome(entry.config_path || path.join(openclawHome, "openclaw.json")));
    let config;
    try {
      config = readJson(configPath);
    } catch (error) {
      return { name: "openclaw", attempted: true, ok: false, repaired: false, error: error.message };
    }
    if (!config || typeof config !== "object") {
      return { name: "openclaw", attempted: true, ok: false, repaired: false, error: `missing ${configPath}` };
    }
    const extensionPath = path.join(currentRuntimePath, ".openclaw", "extensions", "agent-wallet");
    const walletPackageRoot = path.join(currentRuntimePath, "agent-wallet");
    const pythonBin = resolveVenvPython(currentRuntimePath);
    const plugins = config.plugins && typeof config.plugins === "object" ? config.plugins : (config.plugins = {});
    const load = plugins.load && typeof plugins.load === "object" ? plugins.load : (plugins.load = {});
    const paths = Array.isArray(load.paths) ? load.paths : [];
    load.paths = [
      ...paths.filter((item) => !String(item || "").replaceAll("\\", "/").endsWith("/.openclaw/extensions/agent-wallet")),
      extensionPath,
    ];
    const entries = plugins.entries && typeof plugins.entries === "object" ? plugins.entries : (plugins.entries = {});
    const walletEntry = entries["agent-wallet"];
    if (!walletEntry || typeof walletEntry !== "object") {
      return { name: "openclaw", attempted: false, ok: true, repaired: false, reason: "plugin entry not configured" };
    }
    walletEntry.enabled = true;
    walletEntry.config = walletEntry.config && typeof walletEntry.config === "object" ? walletEntry.config : {};
    walletEntry.config.packageRoot = walletPackageRoot;
    if (pythonBin) walletEntry.config.pythonBin = pythonBin;
    writeJsonAtomic(configPath, config);
    registry.record("openclaw", {
      config_path: configPath,
      extension_path: extensionPath,
      package_root: walletPackageRoot,
      restart_required: true,
    });
    return { name: "openclaw", attempted: true, ok: true, repaired: true, config_path: configPath, restart_required: true };
  }

  function refreshHermes() {
    const entry = registry.managed("hermes") || adoptHermes();
    if (!entry) return null;
    const target = path.resolve(expandHome(entry.plugin_target));
    const envPath = path.resolve(expandHome(entry.env_path));
    const result = repairRuntimeSymlink(
      "hermes",
      target,
      path.join(currentRuntimePath, "hermes", "plugins", "agent_wallet"),
      env,
      { allowExternal: true },
    );
    result.env_repaired = repairHermesEnv(envPath, env);
    result.restart_required = true;
    if (result.ok) {
      registry.record("hermes", { ...entry, plugin_target: target, env_path: envPath, restart_required: true });
    }
    return result;
  }

  function refreshCodex() {
    const entry = registry.managed("codex") || adoptCodex();
    if (!entry) return null;
    const pluginTarget = path.resolve(expandHome(entry.plugin_target || path.join(codexPluginRoot, "agent-wallet")));
    const marketplacePath = path.resolve(expandHome(entry.marketplace_path || codexMarketplacePath));
    const link = repairRuntimeSymlink(
      "codex",
      pluginTarget,
      path.join(currentRuntimePath, "codex", "plugins", "agent-wallet"),
      env,
      { allowExternal: true },
    );
    if (!link.ok) return link;
    const marketplace = ensureCodexMarketplaceEntry({ marketplacePath, pluginName: "agent-wallet" });
    const registration = runHostRefresh(
      "codex",
      ["plugin", "add", `agent-wallet@${marketplace.marketplace_name}`],
      { ...env, CODEX_HOME: entry.codex_home || codexHome },
    );
    registry.record("codex", {
      ...entry,
      plugin_target: pluginTarget,
      marketplace_path: marketplacePath,
      marketplace_name: marketplace.marketplace_name,
      registration_ok: registration.ok,
      restart_required: true,
    });
    return { ...link, ok: link.ok && registration.ok, registration, restart_required: true };
  }

  function refreshClaudeCode() {
    const entry = registry.managed("claude-code") || adoptClaudeCode();
    if (!entry) return null;
    const marketplaceDir = path.resolve(expandHome(entry.marketplace_dir || claudeMarketplaceDir));
    const cacheRoot = path.resolve(
      expandHome(entry.cache_root || env.AGENT_WALLET_CLAUDE_CODE_CACHE_ROOT || "~/.claude/plugins/cache"),
    );
    const pluginTarget = path.resolve(expandHome(entry.plugin_target || path.join(marketplaceDir, "plugins", "agent-wallet")));
    const link = repairRuntimeSymlink(
      "claude-code",
      pluginTarget,
      path.join(currentRuntimePath, "claude-code", "plugins", "agent-wallet"),
      env,
      { allowExternal: true },
    );
    if (!link.ok) return link;
    ensureClaudeCodeMarketplace(
      marketplaceDir,
      path.join(currentRuntimePath, "claude-code", "plugins", "agent-wallet"),
      true,
    );
    const marketplaceAdd = runHostRefresh(
      "claude",
      ["plugin", "marketplace", "add", marketplaceDir, "--scope", "user"],
    );
    const registration = marketplaceAdd.ok
      ? runHostRefresh(
          "claude",
          ["plugin", "install", `agent-wallet@${claudeMarketplaceName}`, "--scope", "user"],
        )
      : { attempted: false, ok: false, error: "marketplace refresh failed", fix: marketplaceAdd.fix };
    const cachePins = pinClaudeCacheCopies({ ...env, AGENT_WALLET_CLAUDE_CODE_CACHE_ROOT: cacheRoot });
    registry.record("claude-code", {
      ...entry,
      marketplace_dir: marketplaceDir,
      plugin_target: pluginTarget,
      cache_root: cacheRoot,
      registration_ok: registration.ok,
      restart_required: true,
    });
    return {
      ...link,
      ok: link.ok && marketplaceAdd.ok && registration.ok,
      marketplace_add: marketplaceAdd,
      registration,
      cache_pins: cachePins,
      restart_required: true,
    };
  }

  function refreshAll() {
    return registry.refreshAll({
      openclaw: refreshOpenclaw,
      hermes: refreshHermes,
      codex: refreshCodex,
      "claude-code": refreshClaudeCode,
    });
  }

  return { refreshAll };
}
