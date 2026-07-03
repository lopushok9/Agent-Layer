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


def _strip_boot_key_line(env_path: Path) -> bool:
    """Remove only the AGENT_WALLET_BOOT_KEY line; preserve all other vars.

    Returns True if the file changed.
    """
    try:
        lines = env_path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return False
    kept = [ln for ln in lines if not ln.strip().startswith(_ENV_LINE_PREFIX)]
    if len(kept) == len(lines):
        return False
    atomic_write_text(env_path, ("\n".join(kept) + "\n") if kept else "", mode=0o600)
    return True


def _sweep_plaintext(home: Path) -> tuple[int, bool]:
    """Strip the boot-key line from every runtime .env; delete the shared boot-key file."""
    runtime = home / "agent-wallet-runtime"
    swept = 0
    for env_path in runtime.glob("**/.env"):
        try:
            if _strip_boot_key_line(env_path):
                swept += 1
        except Exception:
            continue  # best-effort; re-runs next start
    removed = False
    boot_file = runtime / "boot-key"
    try:
        boot_file.unlink()
        removed = True
    except FileNotFoundError:
        pass
    except OSError:
        pass
    return swept, removed


def migrate_boot_key_to_keystore() -> dict:
    """Move a legacy plaintext boot key into the keystore, verify, then sweep plaintext."""
    store = resolve_keystore()

    # Already migrated: keystore holds it and no plaintext file remains to sweep.
    home = resolve_openclaw_home()
    boot_file = home / "agent-wallet-runtime" / "boot-key"
    if read_boot_key_from_keystore() and not boot_file.exists():
        return {"migrated": False, "backend": store.backend_id, "swept_env_files": 0,
                "removed_boot_key_file": False, "reason": "already-migrated"}

    legacy_key = _read_legacy_boot_key()
    if not legacy_key:
        return {"migrated": False, "backend": store.backend_id, "swept_env_files": 0,
                "removed_boot_key_file": False, "reason": "no-legacy-key"}

    # Do not sweep into a plaintext fallback: that offers no at-rest improvement,
    # and the user explicitly chose to stay on the current file in that case.
    if isinstance(store, PlaintextFileStore):
        return {"migrated": False, "backend": store.backend_id, "swept_env_files": 0,
                "removed_boot_key_file": False, "reason": "no-os-keystore"}

    try:
        store.set(BOOT_KEY_ITEM, legacy_key)
    except Exception as exc:
        return {"migrated": False, "backend": store.backend_id, "swept_env_files": 0,
                "removed_boot_key_file": False, "reason": f"keystore-set-failed: {exc}"}

    # Verify-before-delete.
    if read_boot_key_from_keystore() != legacy_key:
        return {"migrated": False, "backend": store.backend_id, "swept_env_files": 0,
                "removed_boot_key_file": False, "reason": "verify-failed"}

    swept, removed = _sweep_plaintext(home)
    return {"migrated": True, "backend": store.backend_id, "swept_env_files": swept,
            "removed_boot_key_file": removed, "reason": "ok"}
