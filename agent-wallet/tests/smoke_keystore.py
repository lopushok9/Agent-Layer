"""Smoke test for the cross-platform KeyStore abstraction."""
from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agent_wallet.keystore import (  # noqa: E402
    PlaintextFileStore,
    resolve_keystore,
)


def main() -> None:
    temp_home = Path("/tmp/openclaw-keystore-smoke")
    if temp_home.exists():
        shutil.rmtree(temp_home)
    os.environ["OPENCLAW_HOME"] = str(temp_home)
    os.environ["AGENT_WALLET_KEYSTORE_SERVICE"] = "ai.agentlayer.wallet.smoketest"

    # PlaintextFileStore round-trips and is always available.
    store = PlaintextFileStore()
    assert store.available() is True
    assert store.get("boot_key") is None
    store.set("boot_key", "secret-value-123")
    assert store.get("boot_key") == "secret-value-123"
    store.delete("boot_key")
    assert store.get("boot_key") is None

    # resolve_keystore returns something usable and round-trips.
    resolved = resolve_keystore()
    assert resolved.backend_id in {
        "macos-keychain",
        "windows-dpapi",
        "linux-secretservice",
        "plaintext-file",
    }
    resolved.set("boot_key", "round-trip")
    assert resolved.get("boot_key") == "round-trip"
    resolved.delete("boot_key")
    assert resolved.get("boot_key") is None

    print("smoke_keystore OK:", resolved.backend_id)


if __name__ == "__main__":
    main()
