"""Regression: set() must not hang when the keychain item already exists with a
foreign ACL.

The 0.1.61 install hang: a keychain item created by an earlier install (or any
other tool) WITHOUT `-A` carries a partition-list-restricted ACL. Updating such
an item in place (`add-generic-password -U`) or touching its partition list
pops a background GUI keychain dialog and stalls non-interactive installs until
the subprocess timeout. MacKeychainStore.set() avoids this by recreating the
item fresh (delete + add with `-A`).

This test pins that behavior: pre-create the item WITHOUT -A (simulating the
stale item an older install leaves behind), then assert set() completes fast
and round-trips. A regression back to in-place update would either raise
(headless CI) or blow past the time bound (GUI prompt -> 10s timeout).

macOS-only; skips elsewhere. Uses a throwaway keystore service so no real boot
key is ever touched.
"""

from __future__ import annotations

import os
import platform
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

_SECURITY_BIN = "/usr/bin/security"
_TEST_SERVICE = "ai.agentlayer.wallet.acltest"


def main() -> None:
    if platform.system() != "Darwin" or not Path(_SECURITY_BIN).exists():
        print("smoke_keystore_preexisting_acl SKIP: macOS-only")
        return

    temp_home = Path(tempfile.mkdtemp(prefix="openclaw-ks-acl-"))
    os.environ["OPENCLAW_HOME"] = str(temp_home)
    os.environ["AGENT_WALLET_KEYSTORE_SERVICE"] = _TEST_SERVICE
    for var in ("AGENT_WALLET_BOOT_KEY", "AGENT_WALLET_BOOT_KEY_FILE", "AGENT_WALLET_KEYSTORE_BACKEND"):
        os.environ.pop(var, None)

    from agent_wallet.keystore import BOOT_KEY_ITEM, MacKeychainStore

    store = MacKeychainStore()
    assert store.available(), "macOS Keychain backend unavailable on Darwin host"

    try:
        # Clean slate, then plant the hostile fixture: an item created WITHOUT
        # -A and trusting only a foreign app (-T /bin/ls). That mirrors the item
        # an older install / other writer leaves behind: partition-list present
        # AND security(1) not in the item's trusted-app ACL, so any in-place
        # update (-U) or partition-list edit needs interactive confirmation.
        store.delete(BOOT_KEY_ITEM)
        subprocess.run(
            [_SECURITY_BIN, "add-generic-password",
             "-s", _TEST_SERVICE, "-a", BOOT_KEY_ITEM, "-w", "stale-old-boot-key",
             "-T", "/bin/ls"],
            check=True, capture_output=True, timeout=10,
        )

        # set() over the foreign-ACL item must be prompt-free and fast. The
        # backend's own subprocess timeout is 10s, and a partition-list dialog
        # stalls the security call all the way to that cap — so a healthy
        # delete+add must land well under it.
        fresh = "fresh-" + "f00d" * 12
        started = time.monotonic()
        store.set(BOOT_KEY_ITEM, fresh)
        elapsed = time.monotonic() - started
        assert elapsed < 8.0, f"set() over a foreign-ACL item took {elapsed:.1f}s (prompt/hang?)"
        assert store.get(BOOT_KEY_ITEM) == fresh, "round-trip after ACL takeover failed"

        # And the item we just wrote must itself be safely overwritable.
        started = time.monotonic()
        store.set(BOOT_KEY_ITEM, fresh + "-v2")
        elapsed = time.monotonic() - started
        assert elapsed < 8.0, f"second set() took {elapsed:.1f}s"
        assert store.get(BOOT_KEY_ITEM) == fresh + "-v2", "overwrite round-trip failed"
    finally:
        try:
            store.delete(BOOT_KEY_ITEM)
        except Exception:
            pass
        shutil.rmtree(temp_home, ignore_errors=True)

    assert store.get(BOOT_KEY_ITEM) is None, "keystore item lingered after cleanup"
    print("smoke_keystore_preexisting_acl OK")


if __name__ == "__main__":
    main()
