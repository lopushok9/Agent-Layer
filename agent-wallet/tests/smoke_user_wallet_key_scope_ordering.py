"""Encrypted user wallets try the envelope-recorded key scope first.

Without the recorded scope, per-user derivation enabled means the loader
tries the per-user-derived key first and pays a full (wasted) KDF when the
file is actually encrypted with the global master key. The envelope metadata
now records which scope encrypted the file so the matching candidate goes
first; files without the marker keep the legacy order.
"""
from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

TEMP_HOME = Path("/tmp/openclaw-key-scope-ordering-smoke")
MASTER_KEY = "smoke-master-key"
USER_ID = "scope-smoke-user"


def main() -> None:
    if TEMP_HOME.exists():
        shutil.rmtree(TEMP_HOME)
    TEMP_HOME.mkdir(parents=True)
    os.environ["OPENCLAW_HOME"] = str(TEMP_HOME)
    os.environ["AGENT_WALLET_KEYSTORE_BACKEND"] = "plaintext"
    os.environ["AGENT_WALLET_BOOT_KEY"] = "smoke-boot-key"
    os.environ["AGENT_WALLET_ENCRYPT_USER_WALLETS"] = "1"

    import agent_wallet.config as config

    config.reload_settings()

    from agent_wallet import encrypted_storage, sealed_keys, user_wallets

    assert config.use_per_user_key_derivation(), "test requires per-user derivation on"
    sealed_keys.seal_keys("smoke-boot-key", {"master_key": MASTER_KEY})

    from agent_wallet.bootstrap import generate_solana_wallet_material

    material = generate_solana_wallet_material()
    network = "mainnet"
    path = user_wallets.resolve_user_wallet_path(USER_ID, network=network)
    path.parent.mkdir(parents=True, exist_ok=True)

    def decrypt_attempts_during_load() -> int:
        """Count decrypt attempts (successful or failed) during a wallet load."""
        attempts = {"n": 0}
        real_decrypt = user_wallets.decrypt_secret_material

        def counting_decrypt(raw_text, *, master_key=None):
            attempts["n"] += 1
            return real_decrypt(raw_text, master_key=master_key)

        user_wallets.decrypt_secret_material = counting_decrypt
        try:
            encrypted_storage.clear_derived_key_cache()
            secret, fmt, scope = user_wallets._load_user_wallet_secret_material(
                path, user_id=USER_ID, network=network
            )
            assert secret == material["secret_material"]
            assert fmt == "encrypted"
            return attempts["n"]
        finally:
            user_wallets.decrypt_secret_material = real_decrypt

    # 1. File encrypted with the GLOBAL master key and a recorded scope: the
    # loader must try global-master first — exactly one decrypt attempt.
    envelope = encrypted_storage.encrypt_secret_material(
        material["secret_material"],
        master_key=MASTER_KEY,
        metadata={
            "address": material["address"],
            "user_id": USER_ID,
            "network": network,
            "key_scope": "global-master",
        },
    )
    path.write_text(envelope, encoding="utf-8")
    attempts = decrypt_attempts_during_load()
    assert attempts == 1, f"recorded scope must be tried first: {attempts} attempts"

    # 2. Same file WITHOUT the recorded scope keeps the legacy order:
    # per-user-derived first (fails), then global-master — two attempts.
    envelope = encrypted_storage.encrypt_secret_material(
        material["secret_material"],
        master_key=MASTER_KEY,
        metadata={
            "address": material["address"],
            "user_id": USER_ID,
            "network": network,
        },
    )
    path.write_text(envelope, encoding="utf-8")
    attempts = decrypt_attempts_during_load()
    assert attempts == 2, f"legacy files keep the old order: {attempts} attempts"

    # 3. Freshly provisioned wallets record their key scope in the envelope.
    path.unlink()
    pin_path = path.with_suffix(f"{path.suffix}.pin.json")
    if pin_path.exists():
        pin_path.unlink()
    import json

    info = user_wallets.ensure_user_solana_wallet(USER_ID, network=network)
    payload = json.loads(path.read_text(encoding="utf-8"))
    recorded = (payload.get("metadata") or {}).get("key_scope")
    assert recorded == "per-user-derived", f"new wallets must record scope, got {recorded!r}"
    assert info["key_scope"] == "per-user-derived"

    print("smoke_user_wallet_key_scope_ordering OK")


if __name__ == "__main__":
    main()
