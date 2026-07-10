"""Verified keystore selection persists without pinning temporary fallbacks."""

from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

os.environ["OPENCLAW_HOME"] = tempfile.mkdtemp(prefix="openclaw-keystore-state-")
os.environ["AGENT_WALLET_KEYSTORE_SERVICE"] = "ai.agentlayer.wallet.state-smoke"
os.environ.pop("AGENT_WALLET_KEYSTORE_BACKEND", None)

from agent_wallet import keystore  # noqa: E402


def main() -> None:
    home = Path(os.environ["OPENCLAW_HOME"])
    native_values: dict[str, str] = {}
    native_available = True
    original = (
        keystore.MacKeychainStore.available,
        keystore.MacKeychainStore.get,
        keystore.MacKeychainStore.set,
        keystore.MacKeychainStore.delete,
    )
    try:
        keystore.MacKeychainStore.available = lambda _self: native_available
        keystore.MacKeychainStore.get = lambda _self, name: native_values.get(name)
        keystore.MacKeychainStore.set = (
            lambda _self, name, value: native_values.__setitem__(name, value)
        )
        keystore.MacKeychainStore.delete = lambda _self, name: native_values.pop(name, None)

        store = keystore.resolve_keystore()
        assert store.backend_id == "macos-keychain"
        store.set(keystore.BOOT_KEY_ITEM, "verified-native-key")
        state = keystore.record_keystore_backend(store)
        assert state["recorded"] is True, state

        state_path = home / "keystore" / "backend.json"
        payload = json.loads(state_path.read_text(encoding="utf-8"))
        assert payload["backend"] == "macos-keychain", payload

        native_available = False
        keystore.clear_keystore_cache()
        fallback = keystore.resolve_keystore()
        assert fallback.backend_id == "plaintext-file"
        preserved = keystore.record_keystore_backend(fallback)
        assert preserved == {
            "recorded": False,
            "backend": "macos-keychain",
            "fallback_backend": "plaintext-file",
        }
        assert keystore.keystore_backend_status()["fallback_active"] is True

        native_available = True
        keystore.clear_keystore_cache()
        assert keystore.resolve_keystore().backend_id == "macos-keychain"

        os.environ["AGENT_WALLET_KEYSTORE_BACKEND"] = "plaintext"
        keystore.clear_keystore_cache()
        explicit = keystore.resolve_keystore()
        keystore.record_keystore_backend(explicit)
        assert json.loads(state_path.read_text(encoding="utf-8"))["backend"] == "plaintext-file"
    finally:
        (
            keystore.MacKeychainStore.available,
            keystore.MacKeychainStore.get,
            keystore.MacKeychainStore.set,
            keystore.MacKeychainStore.delete,
        ) = original
        shutil.rmtree(home, ignore_errors=True)

    print("smoke_keystore_backend_state: ok")


if __name__ == "__main__":
    main()
