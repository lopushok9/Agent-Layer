"""Startup calls migration exactly once and never raises when it no-ops."""
from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main() -> None:
    temp_home = Path("/tmp/openclaw-boot-startup-smoke")
    if temp_home.exists():
        shutil.rmtree(temp_home)
    os.environ["OPENCLAW_HOME"] = str(temp_home)
    for var in ("AGENT_WALLET_BOOT_KEY", "AGENT_WALLET_BOOT_KEY_FILE"):
        os.environ.pop(var, None)

    import agent_wallet.openclaw_runtime as runtime

    calls = {"n": 0}
    original = runtime.migrate_boot_key_to_keystore

    def counting_migrate():
        calls["n"] += 1
        return {"migrated": False, "reason": "no-legacy-key", "backend": "test",
                "swept_env_files": 0, "removed_boot_key_file": False}

    runtime.migrate_boot_key_to_keystore = counting_migrate
    try:
        runtime._boot_key_migration_done = False  # reset guard
        runtime.ensure_boot_key_migrated_once()
        runtime.ensure_boot_key_migrated_once()
        assert calls["n"] == 1, calls
    finally:
        runtime.migrate_boot_key_to_keystore = original

    print("smoke_boot_key_startup_wiring OK")


if __name__ == "__main__":
    main()
