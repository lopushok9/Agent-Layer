"""Secret-resolution chain is memoized per process and invalidated correctly."""
from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

TEMP_HOME = Path("/tmp/openclaw-secret-caching-smoke")


def main() -> None:
    if TEMP_HOME.exists():
        shutil.rmtree(TEMP_HOME)
    TEMP_HOME.mkdir(parents=True)
    os.environ["OPENCLAW_HOME"] = str(TEMP_HOME)
    os.environ["AGENT_WALLET_KEYSTORE_BACKEND"] = "plaintext"
    os.environ["AGENT_WALLET_BOOT_KEY"] = "smoke-boot-key"

    import agent_wallet.config as config
    from agent_wallet import encrypted_storage, keystore, sealed_keys

    config.reload_settings()

    # 1. resolve_keystore() returns a cached instance.
    store_a = keystore.resolve_keystore()
    store_b = keystore.resolve_keystore()
    assert store_a is store_b, "resolve_keystore must be memoized"

    # 2. unseal_keys() decrypts the sealed file only once for repeated calls.
    sealed_keys.seal_keys("smoke-boot-key", {"master_key": "m1"})
    calls = {"n": 0}
    real_decrypt = sealed_keys.decrypt_secret_material

    def counting_decrypt(raw_text, *, master_key=None):
        calls["n"] += 1
        return real_decrypt(raw_text, master_key=master_key)

    sealed_keys.decrypt_secret_material = counting_decrypt
    try:
        assert sealed_keys.unseal_keys("smoke-boot-key")["master_key"] == "m1"
        assert sealed_keys.unseal_keys("smoke-boot-key")["master_key"] == "m1"
        assert sealed_keys.unseal_keys("smoke-boot-key")["master_key"] == "m1"
        assert calls["n"] == 1, f"expected 1 decrypt, got {calls['n']}"

        # 3. Rewriting the sealed file invalidates the cache.
        sealed_keys.seal_keys("smoke-boot-key", {"master_key": "m2"})
        assert sealed_keys.unseal_keys("smoke-boot-key")["master_key"] == "m2"
        assert calls["n"] == 2, f"expected fresh decrypt after reseal, got {calls['n']}"

        # 4. Mutating the returned dict must not poison the cache.
        leaked = sealed_keys.unseal_keys("smoke-boot-key")
        leaked["master_key"] = "tampered"
        assert sealed_keys.unseal_keys("smoke-boot-key")["master_key"] == "m2"
    finally:
        sealed_keys.decrypt_secret_material = real_decrypt

    # 5. _derive_key results are cached by (kdf, master_key, salt).
    derive_calls = {"n": 0}
    real_kdf = encrypted_storage._kdf_argon2id

    def counting_kdf(master_key, salt):
        derive_calls["n"] += 1
        return real_kdf(master_key, salt)

    encrypted_storage._kdf_argon2id = counting_kdf
    try:
        encrypted_storage.clear_derived_key_cache()
        env = encrypted_storage.encrypt_secret_material(
            "payload", master_key="k1", kdf="argon2id"
        )
        assert encrypted_storage.decrypt_secret_material(env, master_key="k1") == "payload"
        assert encrypted_storage.decrypt_secret_material(env, master_key="k1") == "payload"
        # Decrypt reuses the key derived during encrypt (same master_key+salt),
        # so a full roundtrip costs exactly one KDF.
        assert derive_calls["n"] == 1, f"expected a single derive, got {derive_calls['n']}"

        # A different master key misses the cache.
        env2 = encrypted_storage.encrypt_secret_material(
            "payload2", master_key="k2", kdf="argon2id"
        )
        assert encrypted_storage.decrypt_secret_material(env2, master_key="k2") == "payload2"
        assert derive_calls["n"] == 2, f"expected a second derive for k2, got {derive_calls['n']}"
    finally:
        encrypted_storage._kdf_argon2id = real_kdf

    # 6. clear_secret_caches() resets the keystore cache too.
    config.clear_secret_caches()
    assert keystore.resolve_keystore() is not store_a, "clear must drop keystore cache"

    # 7. reload_settings() clears caches as well.
    store_c = keystore.resolve_keystore()
    config.reload_settings()
    assert keystore.resolve_keystore() is not store_c, "reload_settings must clear caches"

    print("smoke_secret_resolution_caching OK")


if __name__ == "__main__":
    main()
