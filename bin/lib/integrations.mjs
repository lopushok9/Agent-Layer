import fs from "node:fs";
import path from "node:path";

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

  function readRegistry() {
    const payload = readJson(registryPath);
    if (!payload || payload.schema_version !== 1 || typeof payload.integrations !== "object") {
      return { schema_version: 1, integrations: {} };
    }
    return payload;
  }

  function record(name, details = {}) {
    const registry = readRegistry();
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
    const integrations = Object.entries(readRegistry().integrations)
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
    return { in_sync: integrations.every((entry) => entry.in_sync), integrations };
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
