"""Migration must not replace a keystore key with an unverified legacy value."""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


class FakeNativeStore:
    backend_id = "macos-keychain"

    def __init__(self) -> None:
        self.values: dict[str, str] = {}
        self.set_calls: list[tuple[str, str]] = []

    def available(self) -> bool:
        return True

    def get(self, name: str) -> str | None:
        return self.values.get(name)

    def set(self, name: str, value: str) -> None:
        self.set_calls.append((name, value))
        self.values[name] = value

    def delete(self, name: str) -> None:
        self.values.pop(name, None)


def main() -> None:
    temp_home = Path(tempfile.mkdtemp(prefix="agentlayer-stale-migration-"))
    original_env = {
        name: os.environ.get(name)
        for name in (
            "OPENCLAW_HOME",
            "AGENT_WALLET_BOOT_KEY",
            "AGENT_WALLET_BOOT_KEY_FILE",
            "AGENT_WALLET_KEYSTORE_BACKEND",
            "AGENT_WALLET_KEYSTORE_SERVICE",
        )
    }
    os.environ["OPENCLAW_HOME"] = str(temp_home)
    os.environ["AGENT_WALLET_KEYSTORE_BACKEND"] = "auto"
    os.environ["AGENT_WALLET_KEYSTORE_SERVICE"] = "ai.agentlayer.wallet.stale-migration-test"
    os.environ.pop("AGENT_WALLET_BOOT_KEY", None)

    from agent_wallet import boot_key_migration as migration
    from agent_wallet import config, keystore
    from agent_wallet.sealed_keys import seal_keys

    original_resolvers = (
        keystore.resolve_keystore,
        migration.resolve_keystore,
        keystore.read_legacy_unscoped_boot_key,
    )
    original_settings = (
        config.settings.agent_wallet_boot_key,
        config.settings.agent_wallet_boot_key_file,
    )
    fake_store = FakeNativeStore()
    boot_file = temp_home / "agent-wallet-runtime" / "boot-key"
    boot_file.parent.mkdir(parents=True)
    os.environ["AGENT_WALLET_BOOT_KEY_FILE"] = str(boot_file)
    config.settings.agent_wallet_boot_key = ""
    config.settings.agent_wallet_boot_key_file = str(boot_file)

    try:
        seal_keys("correct-existing-boot-key", {"master_key": "sealed-master-key"})
        keystore.resolve_keystore = lambda: fake_store
        migration.resolve_keystore = lambda: fake_store

        boot_file.write_text("stale-wrong-boot-key\n", encoding="utf-8")
        config.clear_secret_caches()
        rejected = migration.migrate_boot_key_to_keystore()
        assert rejected["migrated"] is False, rejected
        assert rejected["reason"] == "no-legacy-key", rejected
        assert fake_store.set_calls == [], fake_store.set_calls
        assert boot_file.exists(), "rejected legacy key must remain available for diagnosis"

        # A pre-home-scoping native key may be copied into the new scoped
        # service, but only after it decrypts this home's sealed bundle.
        os.environ.pop("AGENT_WALLET_KEYSTORE_SERVICE", None)
        keystore.read_legacy_unscoped_boot_key = lambda: "correct-existing-boot-key"
        config.clear_secret_caches()
        migrated = migration.migrate_boot_key_to_keystore()
        assert migrated["migrated"] is True, migrated
        assert fake_store.get(keystore.BOOT_KEY_ITEM) == "correct-existing-boot-key"
        assert fake_store.set_calls == [
            (keystore.BOOT_KEY_ITEM, "correct-existing-boot-key")
        ]
        assert boot_file.exists(), "unrelated stale plaintext must not be swept"
    finally:
        (
            keystore.resolve_keystore,
            migration.resolve_keystore,
            keystore.read_legacy_unscoped_boot_key,
        ) = original_resolvers
        (
            config.settings.agent_wallet_boot_key,
            config.settings.agent_wallet_boot_key_file,
        ) = original_settings
        for name, value in original_env.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value
        config.clear_secret_caches()
        shutil.rmtree(temp_home, ignore_errors=True)

    print("smoke_boot_key_migration_rejects_stale: ok")


if __name__ == "__main__":
    main()
