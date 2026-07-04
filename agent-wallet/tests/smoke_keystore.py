"""Smoke test for the cross-platform KeyStore abstraction."""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import agent_wallet.keystore as keystore  # noqa: E402
from agent_wallet.keystore import (  # noqa: E402
    MacKeychainStore,
    PlaintextFileStore,
    resolve_keystore,
)


def main() -> None:
    temp_home = Path("/tmp/openclaw-keystore-smoke")
    if temp_home.exists():
        shutil.rmtree(temp_home)
    os.environ["OPENCLAW_HOME"] = str(temp_home)
    os.environ["AGENT_WALLET_KEYSTORE_SERVICE"] = "ai.agentlayer.wallet.smoketest"
    os.environ.pop("AGENT_WALLET_KEYSTORE_BACKEND", None)

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

    original_macos_available = MacKeychainStore.available
    original_macos_get = MacKeychainStore.get
    original_macos_set = MacKeychainStore.set
    original_macos_delete = MacKeychainStore.delete
    try:
        fake_store: dict[str, str] = {}

        MacKeychainStore.available = lambda _self: True
        MacKeychainStore.get = lambda _self, name: fake_store.get(name)
        MacKeychainStore.set = lambda _self, name, value: fake_store.__setitem__(name, value)
        MacKeychainStore.delete = lambda _self, name: fake_store.pop(name, None)
        os.environ["AGENT_WALLET_KEYSTORE_BACKEND"] = "macos-keychain"
        assert resolve_keystore().backend_id == "macos-keychain"
    finally:
        os.environ.pop("AGENT_WALLET_KEYSTORE_BACKEND", None)
        MacKeychainStore.available = original_macos_available
        MacKeychainStore.get = original_macos_get
        MacKeychainStore.set = original_macos_set
        MacKeychainStore.delete = original_macos_delete

    original_subprocess_run = keystore.subprocess.run
    try:
        def timeout_run(*_args, **_kwargs):
            raise subprocess.TimeoutExpired(["fake-security"], 0.01)

        keystore.subprocess.run = timeout_run
        timed_out = keystore._run(["fake-security"], timeout=0.01)
        assert timed_out.returncode == 124
    finally:
        keystore.subprocess.run = original_subprocess_run

    # set() must be prompt-free: delete the existing item, then add with -A, and
    # NEVER call set-generic-password-partition-list (the GUI-prompt source).
    original_run = keystore._run
    try:
        calls: list[list[str]] = []

        def fake_run(argv: list[str], **_kwargs):
            calls.append(argv)
            return subprocess.CompletedProcess(argv, 0, "", "")

        keystore._run = fake_run
        MacKeychainStore().set("boot_key", "secret-value-456")
        assert any("delete-generic-password" in call for call in calls), calls
        add_calls = [call for call in calls if "add-generic-password" in call]
        assert add_calls, calls
        assert "-A" in add_calls[0], add_calls[0]
        assert not any(
            "set-generic-password-partition-list" in call for call in calls
        ), calls
    finally:
        keystore._run = original_run

    print("smoke_keystore OK:", resolved.backend_id)


if __name__ == "__main__":
    main()
