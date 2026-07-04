"""Transparent, verified migration of the boot key into the OS keystore.

Runs at backend startup. Non-destructive: plaintext is swept ONLY after the
keystore read-back verifies. Idempotent and best-effort — a partial sweep
re-runs cleanly next start. See BOOT_KEY_KEYCHAIN_ARCHITECTURE.md.
"""

from __future__ import annotations

import os
from pathlib import Path

from agent_wallet.config import (
    read_boot_key_from_keystore,
    resolve_openclaw_home,
    settings,
)
from agent_wallet.file_ops import atomic_write_text
from agent_wallet.keystore import BOOT_KEY_ITEM, PlaintextFileStore, resolve_keystore

_ENV_LINE_PREFIX = "AGENT_WALLET_BOOT_KEY="


def _read_legacy_boot_key() -> str:
    """The authoritative live key from legacy sources only (env override -> file)."""
    direct = os.getenv("AGENT_WALLET_BOOT_KEY", settings.agent_wallet_boot_key).strip()
    if direct:
        return direct
    key_file = os.getenv("AGENT_WALLET_BOOT_KEY_FILE", settings.agent_wallet_boot_key_file).strip()
    if key_file:
        try:
            return Path(key_file).expanduser().read_text(encoding="utf-8").strip()
        except OSError:
            return ""
    return ""


def _env_boot_key_value(line: str) -> str | None:
    """Return the boot-key value on an AGENT_WALLET_BOOT_KEY= line, else None."""
    stripped = line.strip()
    if not stripped.startswith(_ENV_LINE_PREFIX):
        return None
    return stripped[len(_ENV_LINE_PREFIX):].strip().strip('"').strip("'")


def _strip_boot_key_line(env_path: Path, expected: str) -> bool:
    """Remove only the AGENT_WALLET_BOOT_KEY line whose value == expected.

    Preserve all other vars, and never strip a line carrying a *different* value
    (that would signal a key mismatch a human should look at). Returns True if
    the file changed.
    """
    try:
        lines = env_path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return False
    kept = [ln for ln in lines if _env_boot_key_value(ln) != expected]
    if len(kept) == len(lines):
        return False
    atomic_write_text(env_path, ("\n".join(kept) + "\n") if kept else "", mode=0o600)
    return True


def _candidate_env_files(runtime: Path) -> list[Path]:
    """Boot-key .env locations to sweep, deduped.

    Deliberately bounded: a recursive ``**/.env`` walk descends into the hundreds
    of ``node_modules`` trees under the release dirs and effectively hangs onboarding
    (observed: 650+ node_modules, glob never returns). The boot key was only ever
    written to ``releases/<v>/agent-wallet/.env``; ``current``/``previous`` are
    symlinks into ``releases`` and are resolved to dedupe against their targets.
    """
    candidates = list(runtime.glob("releases/*/agent-wallet/.env"))
    candidates.append(runtime / "current" / "agent-wallet" / ".env")
    candidates.append(runtime / "previous" / "agent-wallet" / ".env")
    seen: set[str] = set()
    out: list[Path] = []
    for path in candidates:
        try:
            key = str(path.resolve())
        except OSError:
            key = str(path)
        if key in seen:
            continue
        seen.add(key)
        if path.exists():
            out.append(path)
    return out


def _sweep_plaintext(home: Path, expected: str) -> tuple[int, bool]:
    """Strip matching boot-key lines from every runtime .env; delete the boot-key file.

    Idempotent and value-scoped: only plaintext equal to the authoritative
    keystore key is removed, so re-running after a fresh installer write (which
    re-emits the same key) cleans it up on the next start.
    """
    runtime = home / "agent-wallet-runtime"
    swept = 0
    for env_path in _candidate_env_files(runtime):
        try:
            if _strip_boot_key_line(env_path, expected):
                swept += 1
        except Exception:
            continue  # best-effort; re-runs next start
    removed = False
    boot_file = runtime / "boot-key"
    try:
        if boot_file.read_text(encoding="utf-8").strip() == expected:
            boot_file.unlink()
            removed = True
    except FileNotFoundError:
        pass
    except OSError:
        pass
    return swept, removed


def migrate_boot_key_to_keystore() -> dict:
    """Move a legacy plaintext boot key into the keystore, verify, then sweep plaintext.

    Runs on every startup (guarded once per process). When the keystore already
    holds the key, it still re-sweeps any plaintext an installer re-emitted, so a
    per-release .env write never re-establishes a permanent leak.
    """
    store = resolve_keystore()
    home = resolve_openclaw_home()

    # Do not sweep into a plaintext fallback: that offers no at-rest improvement,
    # and the user explicitly chose to stay on the current file in that case.
    if isinstance(store, PlaintextFileStore):
        return {"migrated": False, "backend": store.backend_id, "swept_env_files": 0,
                "removed_boot_key_file": False, "reason": "no-os-keystore"}

    authoritative = read_boot_key_from_keystore()
    first_time = False
    if not authoritative:
        legacy_key = _read_legacy_boot_key()
        if not legacy_key:
            return {"migrated": False, "backend": store.backend_id, "swept_env_files": 0,
                    "removed_boot_key_file": False, "reason": "no-legacy-key"}
        try:
            store.set(BOOT_KEY_ITEM, legacy_key)
        except Exception as exc:
            return {"migrated": False, "backend": store.backend_id, "swept_env_files": 0,
                    "removed_boot_key_file": False, "reason": f"keystore-set-failed: {exc}"}
        # Verify-before-delete.
        if read_boot_key_from_keystore() != legacy_key:
            return {"migrated": False, "backend": store.backend_id, "swept_env_files": 0,
                    "removed_boot_key_file": False, "reason": "verify-failed"}
        authoritative = legacy_key
        first_time = True

    swept, removed = _sweep_plaintext(home, authoritative)
    migrated = first_time or swept > 0 or removed
    return {"migrated": migrated, "backend": store.backend_id, "swept_env_files": swept,
            "removed_boot_key_file": removed,
            "reason": "ok" if migrated else "already-clean"}
