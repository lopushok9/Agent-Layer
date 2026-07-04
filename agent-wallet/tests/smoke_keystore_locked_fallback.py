"""Locked default keychain must resolve to the plaintext fallback, bounded in
time — never hang the install.

Real-user scenario the CI matrix's freshly-unlocked keychain never exercises:
the login keychain is locked (SSH session, after sleep/reboot, screen lock
policies). Every security(1) call against a locked keychain either fails fast
("user interaction is not allowed") or stalls on an unlock dialog until the
backend's 10s subprocess timeout. Either way _backend_usable must report the
Keychain backend unusable, and resolve_keystore() must land on plaintext-file
within a bounded number of those timeouts.

Opt-in via AGENT_WALLET_LOCKED_KEYCHAIN_TEST=1 because it assumes the CALLER
has already locked the default keychain — CI locks its throwaway
ci.keychain-db first. Never lock a dev machine's real login keychain for this.
"""

from __future__ import annotations

import os
import platform
import shutil
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main() -> None:
    if os.environ.get("AGENT_WALLET_LOCKED_KEYCHAIN_TEST", "").strip() != "1":
        print("smoke_keystore_locked_fallback SKIP: set AGENT_WALLET_LOCKED_KEYCHAIN_TEST=1 "
              "after locking the default keychain (CI-only)")
        return
    if platform.system() != "Darwin":
        print("smoke_keystore_locked_fallback SKIP: macOS-only")
        return

    temp_home = Path(tempfile.mkdtemp(prefix="openclaw-ks-locked-"))
    os.environ["OPENCLAW_HOME"] = str(temp_home)
    os.environ["AGENT_WALLET_KEYSTORE_SERVICE"] = "ai.agentlayer.wallet.lockedtest"
    for var in ("AGENT_WALLET_BOOT_KEY", "AGENT_WALLET_BOOT_KEY_FILE", "AGENT_WALLET_KEYSTORE_BACKEND"):
        os.environ.pop(var, None)

    from agent_wallet.keystore import BOOT_KEY_ITEM, resolve_keystore

    try:
        # Resolution against a locked keychain: the usability probe burns at
        # most a few 10s subprocess timeouts (get + delete + add), so anything
        # near a minute means an unbounded prompt leaked through.
        started = time.monotonic()
        store = resolve_keystore()
        elapsed = time.monotonic() - started
        print(f"resolved_backend={store.backend_id} in {elapsed:.1f}s")
        assert store.backend_id == "plaintext-file", (
            f"locked keychain must fall back to plaintext-file, got {store.backend_id!r}"
        )
        assert elapsed < 45.0, f"resolve_keystore took {elapsed:.1f}s against a locked keychain"

        # The fallback must actually work end-to-end so the install still has a
        # place to put the boot key.
        secret = "locked-fallback-" + "c4fe" * 10
        store.set(BOOT_KEY_ITEM, secret)
        assert store.get(BOOT_KEY_ITEM) == secret, "plaintext fallback round-trip failed"
        store.delete(BOOT_KEY_ITEM)
    finally:
        shutil.rmtree(temp_home, ignore_errors=True)

    print("smoke_keystore_locked_fallback OK")


if __name__ == "__main__":
    main()
