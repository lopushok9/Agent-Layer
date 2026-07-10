"""Boot-key resolution verifies conflicting candidates against sealed secrets."""

from __future__ import annotations

import atexit
import os
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main() -> None:
    temp_home = Path(tempfile.mkdtemp(prefix="openclaw-boot-key-resolution-"))
    atexit.register(shutil.rmtree, temp_home, ignore_errors=True)
    os.environ["OPENCLAW_HOME"] = str(temp_home)
    os.environ["AGENT_WALLET_KEYSTORE_BACKEND"] = "plaintext"
    os.environ.pop("AGENT_WALLET_BOOT_KEY_FILE", None)

    import agent_wallet.config as config
    from agent_wallet.keystore import BOOT_KEY_ITEM, resolve_keystore
    from agent_wallet.sealed_keys import seal_keys

    config.reload_settings()
    correct_key = "correct-verified-boot-key"
    os.environ["AGENT_WALLET_BOOT_KEY"] = correct_key
    seal_keys(correct_key, {"master_key": "master", "approval_secret": "approval"})

    real_keystore_read = config.read_boot_key_from_keystore

    def fail_keystore_read() -> str:
        raise AssertionError("valid explicit key must not probe the keystore")

    config.read_boot_key_from_keystore = fail_keystore_read
    try:
        assert config.resolve_boot_key() == correct_key
    finally:
        config.read_boot_key_from_keystore = real_keystore_read

    store = resolve_keystore()
    store.set(BOOT_KEY_ITEM, correct_key)
    os.environ["AGENT_WALLET_BOOT_KEY"] = "stale-env-key"
    stale_file = temp_home / "agent-wallet-runtime" / "boot-key"
    stale_file.parent.mkdir(parents=True, exist_ok=True)
    stale_file.write_text("stale-file-key\n", encoding="utf-8")
    config.clear_secret_caches()

    assert config.resolve_boot_key() == correct_key
    status = config.boot_key_resolution_status()
    assert status["source"] == "keystore", status
    assert status["sealed_keys_verified"] is True, status
    assert status["conflict_detected"] is True, status
    assert "environment" in status["rejected_sources"], status
    assert correct_key not in str(status)

    store.delete(BOOT_KEY_ITEM)
    os.environ.pop("AGENT_WALLET_BOOT_KEY", None)
    stale_file.write_text(correct_key + "\n", encoding="utf-8")
    config.clear_secret_caches()
    assert config.resolve_boot_key() == correct_key
    assert config.boot_key_resolution_status()["source"] == "default_file"

    stale_file.write_text("only-wrong-key\n", encoding="utf-8")
    config.clear_secret_caches()
    assert config.resolve_boot_key() == ""
    assert config.boot_key_resolution_status()["available"] is False

    print("smoke_boot_key_verified_resolution: ok")


if __name__ == "__main__":
    main()
