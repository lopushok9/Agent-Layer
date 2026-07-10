"""HKDF-SHA256 envelopes with read compatibility and rollback-safe migration.

The boot key and sealed master key are machine-generated high-entropy secrets,
so argon2id password-hardness buys nothing there while costing ~1s per derive.
New envelopes default to hkdf-sha256; argon2id envelopes remain readable and
normal reads never rewrite them. Explicit migration requires
AGENT_WALLET_ENVELOPE_KDF_MIGRATION=1 and creates a verified backup.
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

TEMP_HOME = Path("/tmp/openclaw-hkdf-envelope-smoke")


def main() -> None:
    if TEMP_HOME.exists():
        shutil.rmtree(TEMP_HOME)
    TEMP_HOME.mkdir(parents=True)
    os.environ["OPENCLAW_HOME"] = str(TEMP_HOME)
    os.environ["AGENT_WALLET_KEYSTORE_BACKEND"] = "plaintext"
    os.environ.pop("AGENT_WALLET_ENVELOPE_KDF", None)
    os.environ.pop("AGENT_WALLET_ENVELOPE_KDF_MIGRATION", None)

    import agent_wallet.config as config

    config.reload_settings()

    from agent_wallet import encrypted_storage, sealed_keys
    from agent_wallet.wallet_layer.base import WalletBackendError

    # 1. Default writes are hkdf-sha256 and roundtrip fast.
    env = encrypted_storage.encrypt_secret_material("hello", master_key="k1")
    assert encrypted_storage.envelope_kdf(env) == "hkdf-sha256", encrypted_storage.envelope_kdf(env)
    encrypted_storage.clear_derived_key_cache()
    started = time.monotonic()
    assert encrypted_storage.decrypt_secret_material(env, master_key="k1") == "hello"
    elapsed = time.monotonic() - started
    assert elapsed < 0.05, f"hkdf decrypt must be instant, took {elapsed:.3f}s"

    # 2. Wrong key still fails cleanly.
    try:
        encrypted_storage.decrypt_secret_material(env, master_key="wrong")
        raise AssertionError("wrong key must fail")
    except WalletBackendError:
        pass

    # 3. argon2id envelopes remain readable (backward compat).
    legacy = encrypted_storage.encrypt_secret_material("legacy", master_key="k1", kdf="argon2id")
    assert encrypted_storage.envelope_kdf(legacy) == "argon2id"
    assert encrypted_storage.decrypt_secret_material(legacy, master_key="k1") == "legacy"

    # 4. Unknown kdf is rejected, not silently misread.
    broken = json.loads(legacy)
    broken["kdf"] = "scrypt"
    try:
        encrypted_storage.decrypt_secret_material(json.dumps(broken), master_key="k1")
        raise AssertionError("unknown kdf must fail")
    except WalletBackendError:
        pass

    # 5. AGENT_WALLET_ENVELOPE_KDF=argon2id forces the old format for writes.
    os.environ["AGENT_WALLET_ENVELOPE_KDF"] = "argon2id"
    forced = encrypted_storage.encrypt_secret_material("forced", master_key="k1")
    assert encrypted_storage.envelope_kdf(forced) == "argon2id"
    os.environ.pop("AGENT_WALLET_ENVELOPE_KDF")

    # 6. Normal reads preserve argon2id for rollback compatibility.
    sealed_path = sealed_keys.resolve_sealed_keys_path()
    sealed_path.parent.mkdir(parents=True, exist_ok=True)
    legacy_sealed = encrypted_storage.encrypt_secret_material(
        json.dumps({"master_key": "m1"}), master_key="boot", kdf="argon2id"
    )
    sealed_path.write_text(legacy_sealed, encoding="utf-8")
    sealed_keys.clear_unseal_cache()
    assert sealed_keys.unseal_keys("boot")["master_key"] == "m1"
    assert encrypted_storage.envelope_kdf(sealed_path.read_text(encoding="utf-8")) == "argon2id"
    backup_path = sealed_path.with_name(sealed_path.name + encrypted_storage.ARGON2ID_BACKUP_SUFFIX)
    assert not backup_path.exists()

    # 7. Opt-in migration writes a verified backup that can restore the old KDF.
    os.environ["AGENT_WALLET_ENVELOPE_KDF_MIGRATION"] = "1"
    sealed_keys.clear_unseal_cache()
    assert sealed_keys.unseal_keys("boot")["master_key"] == "m1"
    assert encrypted_storage.envelope_kdf(sealed_path.read_text(encoding="utf-8")) == "hkdf-sha256"
    assert encrypted_storage.envelope_kdf(backup_path.read_text(encoding="utf-8")) == "argon2id"
    assert encrypted_storage.restore_argon2id_envelope(sealed_path, master_key="boot") is True
    assert encrypted_storage.envelope_kdf(sealed_path.read_text(encoding="utf-8")) == "argon2id"
    sealed_keys.seal_keys("boot", {"master_key": "m2"})
    assert not backup_path.exists(), "logical secret updates must discard stale backups"

    stale_path = TEMP_HOME / "stale-envelope.json"
    stale_path.write_text(legacy, encoding="utf-8")
    encrypted_storage.migrate_envelope_to_hkdf(stale_path, "legacy", master_key="k1")
    stale_path.write_text(
        encrypted_storage.encrypt_secret_material("changed", master_key="k1"),
        encoding="utf-8",
    )
    try:
        encrypted_storage.restore_argon2id_envelope(stale_path, master_key="k1")
        raise AssertionError("stale backup restore must fail")
    except WalletBackendError:
        pass

    # 8. User wallet migration preserves scope/address and creates its own backup.
    os.environ["AGENT_WALLET_BOOT_KEY"] = "boot"
    os.environ["AGENT_WALLET_ENCRYPT_USER_WALLETS"] = "1"
    config.reload_settings()
    sealed_keys.seal_keys("boot", {"master_key": "m1"})

    from agent_wallet import user_wallets
    from agent_wallet.bootstrap import generate_solana_wallet_material

    material = generate_solana_wallet_material()
    network = "mainnet"
    user_id = "hkdf-smoke-user"
    wallet_path = user_wallets.resolve_user_wallet_path(user_id, network=network)
    wallet_path.parent.mkdir(parents=True, exist_ok=True)
    scoped_key = user_wallets._resolve_user_wallet_master_key(user_id, network)
    legacy_wallet = encrypted_storage.encrypt_secret_material(
        material["secret_material"],
        master_key=scoped_key,
        metadata={
            "address": material["address"],
            "user_id": user_id,
            "network": network,
            "key_scope": "per-user-derived",
        },
        kdf="argon2id",
    )
    wallet_path.write_text(legacy_wallet, encoding="utf-8")
    info = user_wallets.ensure_user_solana_wallet(user_id, network=network)
    assert info["address"] == material["address"]
    migrated_wallet = wallet_path.read_text(encoding="utf-8")
    assert encrypted_storage.envelope_kdf(migrated_wallet) == "hkdf-sha256", "wallet must migrate"
    wallet_backup = wallet_path.with_name(wallet_path.name + encrypted_storage.ARGON2ID_BACKUP_SUFFIX)
    assert encrypted_storage.envelope_kdf(wallet_backup.read_text(encoding="utf-8")) == "argon2id"
    payload = json.loads(migrated_wallet)
    assert (payload.get("metadata") or {}).get("key_scope") == "per-user-derived"
    info2 = user_wallets.ensure_user_solana_wallet(user_id, network=network)
    assert info2["address"] == material["address"], "migrated wallet must load"

    print("smoke_hkdf_envelope OK")


if __name__ == "__main__":
    main()
