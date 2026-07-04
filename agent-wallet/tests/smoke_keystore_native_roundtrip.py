"""Real native-keystore round-trip — exercises the ACTUAL OS backend.

Unlike smoke_keystore.py (which mocks the native stores), this drives the real
backend resolve_keystore() selects on the host it runs on:
  - macOS   -> macos-keychain   (security(1))
  - Windows -> windows-dpapi     (PowerShell DPAPI)
  - Linux   -> linux-secretservice when a Secret Service is reachable, else the
               plaintext-file fallback.

Intended for the CI matrix (.github/workflows/keystore-matrix.yml). Set
AGENT_WALLET_EXPECT_BACKEND to assert the exact backend for a given runner.
Uses a throwaway keystore service so it never touches a real boot key.
"""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main() -> None:
    temp_home = Path(tempfile.mkdtemp(prefix="openclaw-ks-native-"))
    os.environ["OPENCLAW_HOME"] = str(temp_home)
    os.environ["AGENT_WALLET_KEYSTORE_SERVICE"] = "ai.agentlayer.wallet.citest"
    for var in ("AGENT_WALLET_BOOT_KEY", "AGENT_WALLET_BOOT_KEY_FILE", "AGENT_WALLET_KEYSTORE_BACKEND"):
        os.environ.pop(var, None)

    import agent_wallet.config as config
    from agent_wallet.keystore import BOOT_KEY_ITEM, resolve_keystore

    config.settings.agent_wallet_boot_key = ""
    config.settings.agent_wallet_boot_key_file = ""

    store = resolve_keystore()
    print(f"platform={sys.platform} resolved_backend={store.backend_id}")

    expect = os.environ.get("AGENT_WALLET_EXPECT_BACKEND", "").strip()
    if expect:
        assert store.backend_id == expect, f"expected backend {expect!r}, got {store.backend_id!r}"

    try:
        # Clean slate, then a real set/get/delete round-trip on the native backend.
        store.delete(BOOT_KEY_ITEM)
        assert store.get(BOOT_KEY_ITEM) is None, "keystore not empty after delete"

        secret = "roundtrip-" + "a1b2c3" * 8  # 58 chars, mixed
        store.set(BOOT_KEY_ITEM, secret)
        got = store.get(BOOT_KEY_ITEM)
        assert got == secret, f"round-trip mismatch: {got!r} != {secret!r}"

        # Full resolver path: with the key in the keystore, resolve_boot_key finds it
        # (no env / no file present).
        assert config.read_boot_key_from_keystore() == secret, "read_boot_key_from_keystore mismatch"
        assert config.resolve_boot_key() == secret, "resolve_boot_key did not read the keystore"

        # Overwrite must round-trip too (delete+add on macOS; store on the others).
        secret2 = secret + "-v2"
        store.set(BOOT_KEY_ITEM, secret2)
        assert store.get(BOOT_KEY_ITEM) == secret2, "overwrite round-trip failed"
    finally:
        try:
            store.delete(BOOT_KEY_ITEM)
        except Exception:
            pass
        shutil.rmtree(temp_home, ignore_errors=True)

    assert store.get(BOOT_KEY_ITEM) is None, "keystore item lingered after cleanup"
    print(f"smoke_keystore_native_roundtrip OK: {store.backend_id}")


if __name__ == "__main__":
    main()
