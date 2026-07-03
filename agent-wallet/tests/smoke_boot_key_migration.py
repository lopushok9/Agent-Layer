"""Migration moves the live boot key into the keystore, verifies, then sweeps plaintext."""
from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agent_wallet.keystore import BOOT_KEY_ITEM, PlaintextFileStore, resolve_keystore  # noqa: E402


def main() -> None:
    temp_home = Path("/tmp/openclaw-boot-migration-smoke")
    if temp_home.exists():
        shutil.rmtree(temp_home)
    os.environ["OPENCLAW_HOME"] = str(temp_home)
    os.environ["AGENT_WALLET_KEYSTORE_SERVICE"] = "ai.agentlayer.wallet.smoketest"
    for var in ("AGENT_WALLET_BOOT_KEY", "AGENT_WALLET_BOOT_KEY_FILE"):
        os.environ.pop(var, None)

    import agent_wallet.config as config
    config.settings.agent_wallet_boot_key = ""
    config.settings.agent_wallet_boot_key_file = ""

    store = resolve_keystore()
    store.delete(BOOT_KEY_ITEM)

    if isinstance(store, PlaintextFileStore):
        # No OS keystore on this host: migration deliberately no-ops (fallback path).
        print("smoke_boot_key_migration SKIPPED: no OS keystore on this host")
        return

    try:
        # Legacy layout: two release .env files + the shared boot-key file all carry the key.
        runtime = temp_home / "agent-wallet-runtime"
        boot_file = runtime / "boot-key"
        boot_file.parent.mkdir(parents=True, exist_ok=True)
        boot_file.write_text("LIVE-BOOT-KEY\n", encoding="utf-8")
        os.environ["AGENT_WALLET_BOOT_KEY_FILE"] = str(boot_file)

        env_a = runtime / "releases" / "0.1.57" / "agent-wallet" / ".env"
        env_b = runtime / "releases" / "0.1.58" / "agent-wallet" / ".env"
        for env in (env_a, env_b):
            env.parent.mkdir(parents=True, exist_ok=True)
            env.write_text(
                "SOLANA_NETWORK=mainnet\nAGENT_WALLET_BOOT_KEY=LIVE-BOOT-KEY\nHTTP_TIMEOUT=10\n",
                encoding="utf-8",
            )

        from agent_wallet.boot_key_migration import migrate_boot_key_to_keystore

        result = migrate_boot_key_to_keystore()
        assert result["migrated"] is True, result
        assert result["swept_env_files"] == 2, result

        # Key is now in the keystore.
        assert config.read_boot_key_from_keystore() == "LIVE-BOOT-KEY"

        # Plaintext is gone: boot-key file removed, AGENT_WALLET_BOOT_KEY lines stripped,
        # but OTHER env vars preserved.
        assert not boot_file.exists()
        for env in (env_a, env_b):
            body = env.read_text(encoding="utf-8")
            assert "AGENT_WALLET_BOOT_KEY" not in body, body
            assert "SOLANA_NETWORK=mainnet" in body
            assert "HTTP_TIMEOUT=10" in body

        # Idempotent: a second run with nothing left to sweep no-ops.
        os.environ.pop("AGENT_WALLET_BOOT_KEY_FILE", None)
        again = migrate_boot_key_to_keystore()
        assert again["migrated"] is False, again

        # Treadmill guard: an installer re-emits the same key into a fresh .env.
        # The next migration must re-sweep it (keystore already holds the key).
        env_c = runtime / "releases" / "0.1.59" / "agent-wallet" / ".env"
        env_c.parent.mkdir(parents=True, exist_ok=True)
        env_c.write_text(
            "SOLANA_NETWORK=mainnet\nAGENT_WALLET_BOOT_KEY=LIVE-BOOT-KEY\n",
            encoding="utf-8",
        )
        reswept = migrate_boot_key_to_keystore()
        assert reswept["migrated"] is True, reswept
        assert reswept["swept_env_files"] == 1, reswept
        assert "AGENT_WALLET_BOOT_KEY" not in env_c.read_text(encoding="utf-8")

        # Safety: a DIFFERENT key value is left untouched (possible mismatch to
        # surface to a human, not silently delete).
        env_d = runtime / "releases" / "0.1.60" / "agent-wallet" / ".env"
        env_d.parent.mkdir(parents=True, exist_ok=True)
        env_d.write_text("AGENT_WALLET_BOOT_KEY=SOME-OTHER-KEY\n", encoding="utf-8")
        guarded = migrate_boot_key_to_keystore()
        assert guarded["swept_env_files"] == 0, guarded
        assert "SOME-OTHER-KEY" in env_d.read_text(encoding="utf-8")

        print("smoke_boot_key_migration OK:", result["backend"])
    finally:
        store.delete(BOOT_KEY_ITEM)


if __name__ == "__main__":
    main()
