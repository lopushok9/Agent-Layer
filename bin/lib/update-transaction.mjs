import crypto from "node:crypto";
import fs from "node:fs";
import os from "node:os";
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

function uniquePath(target) {
  if (!fs.existsSync(target)) return target;
  let counter = 2;
  while (fs.existsSync(`${target}-${counter}`)) counter += 1;
  return `${target}-${counter}`;
}

function readLink(target) {
  try {
    return fs.lstatSync(target).isSymbolicLink() ? fs.readlinkSync(target) : null;
  } catch (error) {
    if (error?.code === "ENOENT") return null;
    throw error;
  }
}

function processIsRunning(pid) {
  if (!Number.isInteger(pid) || pid <= 0) return false;
  try {
    process.kill(pid, 0);
    return true;
  } catch (error) {
    return error?.code !== "ESRCH";
  }
}

export function createUpdateTransactionManager({ runtimeBase, packageVersion, env = process.env }) {
  const base = path.resolve(runtimeBase);
  const journalPath = path.join(base, "update-journal.json");
  const lockPath = path.join(base, "update.lock");

  function readJournal() {
    try {
      return readJson(journalPath);
    } catch (error) {
      return { schema_version: 1, state: "corrupt", error: error.message };
    }
  }

  function writeJournal(state, details = {}) {
    writeJsonAtomic(journalPath, {
      ...details,
      schema_version: 2,
      state,
      version: details.version || packageVersion,
      updated_at: new Date().toISOString(),
    });
  }

  function runtimeOwned(candidate) {
    if (!candidate) return false;
    const relative = path.relative(base, path.resolve(candidate));
    return relative !== "" && !relative.startsWith(`..${path.sep}`) && !path.isAbsolute(relative);
  }

  function interruptedPath(version) {
    return uniquePath(
      path.join(base, "releases", `.interrupted-${version || "unknown"}-${Date.now()}`),
    );
  }

  function acquireLock(allowStaleRetry = true) {
    const ownerPath = path.join(lockPath, "owner.json");
    const token = crypto.randomUUID();
    fs.mkdirSync(base, { recursive: true });
    try {
      fs.mkdirSync(lockPath);
    } catch (error) {
      if (error?.code !== "EEXIST") throw error;
      let owner = null;
      try {
        owner = readJson(ownerPath);
      } catch {
        // An unreadable lock is not safe to steal automatically.
      }
      const stale = owner?.hostname === os.hostname() && !processIsRunning(Number(owner.pid));
      if (stale && allowStaleRetry) {
        fs.rmSync(lockPath, { recursive: true, force: true });
        return acquireLock(false);
      }
      return {
        ok: false,
        path: lockPath,
        owner: owner ? { pid: owner.pid, hostname: owner.hostname, started_at: owner.started_at } : null,
      };
    }
    try {
      writeJsonAtomic(ownerPath, {
        schema_version: 1,
        pid: process.pid,
        hostname: os.hostname(),
        token,
        started_at: new Date().toISOString(),
      });
    } catch (error) {
      fs.rmSync(lockPath, { recursive: true, force: true });
      throw error;
    }
    return { ok: true, path: lockPath, owner_path: ownerPath, token };
  }

  function releaseLock(lock) {
    if (!lock?.ok) return;
    try {
      const owner = readJson(lock.owner_path);
      if (owner?.token === lock.token) fs.rmSync(lock.path, { recursive: true, force: true });
    } catch {
      // Never remove a lock whose ownership can no longer be verified.
    }
  }

  function recover() {
    const journal = readJournal();
    if (!journal || ["committed", "failed", "recovered"].includes(journal.state)) {
      return { attempted: false, ok: true, reason: "no interrupted update" };
    }
    if (journal.state === "corrupt") {
      return { attempted: false, ok: false, reason: "update journal is corrupt", error: journal.error };
    }
    const paths = [journal.staging_root, journal.release_root, journal.replaced_root].filter(Boolean);
    if (paths.some((candidate) => !runtimeOwned(candidate))) {
      return { attempted: false, ok: false, reason: "update journal contains an unsafe path" };
    }
    if (journal.state === "committing") {
      const releaseExists = Boolean(journal.release_root && fs.existsSync(journal.release_root));
      const replacedExists = Boolean(journal.replaced_root && fs.existsSync(journal.replaced_root));
      if (!releaseExists && replacedExists) {
        fs.renameSync(journal.replaced_root, journal.release_root);
        writeJournal("recovered", { ...journal, action: "restored_replaced_release" });
        return { attempted: true, ok: true, action: "restored_replaced_release" };
      }
      if (releaseExists) {
        writeJournal("recovered", { ...journal, action: "release_already_present" });
        return { attempted: true, ok: true, action: "release_already_present" };
      }
      return { attempted: true, ok: false, reason: "interrupted commit has no recoverable release" };
    }
    if (["preparing", "verified"].includes(journal.state)) {
      let quarantined = null;
      if (journal.staging_root && fs.existsSync(journal.staging_root)) {
        quarantined = interruptedPath(journal.version);
        fs.renameSync(journal.staging_root, quarantined);
      }
      writeJournal("recovered", {
        ...journal,
        action: "quarantined_incomplete_staging",
        quarantined_runtime: quarantined,
      });
      return {
        attempted: true,
        ok: true,
        action: "quarantined_incomplete_staging",
        quarantined_runtime: quarantined,
      };
    }
    return { attempted: false, ok: false, reason: `unsupported update journal state: ${journal.state}` };
  }

  function status() {
    const journal = readJournal();
    const state = journal?.state || null;
    const currentPath = path.join(base, "current");
    const currentTarget = readLink(currentPath);
    const currentResolves = Boolean(
      currentTarget && fs.existsSync(path.resolve(path.dirname(currentPath), currentTarget)),
    );
    let lockOwner = null;
    try {
      const owner = readJson(path.join(lockPath, "owner.json"));
      if (owner) {
        lockOwner = {
          pid: owner.pid,
          hostname: owner.hostname,
          started_at: owner.started_at,
          active: owner.hostname === os.hostname() ? processIsRunning(Number(owner.pid)) : null,
        };
      }
    } catch {
      if (fs.existsSync(lockPath)) lockOwner = { unreadable: true };
    }
    return {
      journal_schema_version: journal?.schema_version || null,
      state,
      journal_ok: state !== "corrupt",
      needs_recovery: Boolean(state && !["committed", "failed", "recovered"].includes(state)),
      current_resolves: currentTarget ? currentResolves : null,
      lock: lockOwner,
    };
  }

  function holdLockForTest() {
    const milliseconds = Number.parseInt(String(env.AGENT_WALLET_TEST_HOLD_LOCK_MS || ""), 10);
    if (Number.isFinite(milliseconds) && milliseconds > 0) {
      Atomics.wait(new Int32Array(new SharedArrayBuffer(4)), 0, 0, milliseconds);
    }
  }

  return {
    journalPath,
    lockPath,
    readJournal,
    writeJournal,
    acquireLock,
    releaseLock,
    recover,
    status,
    holdLockForTest,
  };
}
