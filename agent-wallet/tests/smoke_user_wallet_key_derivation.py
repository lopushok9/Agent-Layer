"""Smoke test for per-user wallet key derivation and migration."""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agent_wallet.encrypted_storage import _derive_user_scoped_key, load_wallet_secret_material  # noqa: E402
from agent_wallet.user_wallets import ensure_user_solana_wallet, get_user_wallet_storage_info  # noqa: E402
from agent_wallet.wallet_layer.base import WalletBackendError  # noqa: E402


def main() -> None:
    temp_home = Path("/tmp/openclaw-user-wallet-key-derivation-smoke")
    if temp_home.exists():
        shutil.rmtree(temp_home)

    raw_master_key = "test-master-key-for-user-derivation"
    os.environ["OPENCLAW_HOME"] = str(temp_home)
    os.environ["AGENT_WALLET_MASTER_KEY"] = raw_master_key
    os.environ["AGENT_WALLET_ENCRYPT_USER_WALLETS"] = "true"
    os.environ["AGENT_WALLET_MIGRATE_PLAINTEXT_USER_WALLETS"] = "true"
    os.environ["AGENT_WALLET_PER_USER_KEY_DERIVATION"] = "false"

    legacy = ensure_user_solana_wallet("legacy@example.com", network="devnet")
    legacy_path = Path(legacy["path"])
    original_secret, original_format = load_wallet_secret_material(legacy_path, master_key=raw_master_key)
    assert original_format == "encrypted"
    assert legacy["key_scope"] == "global-master"

    os.environ["AGENT_WALLET_PER_USER_KEY_DERIVATION"] = "true"
    migrated = ensure_user_solana_wallet("legacy@example.com", network="devnet")
    assert migrated["address"] == legacy["address"]
    assert migrated["key_scope"] == "per-user-derived"

    derived_legacy_key = _derive_user_scoped_key(
        raw_master_key,
        user_id="legacy@example.com",
        network="devnet",
    )
    migrated_secret, migrated_format = load_wallet_secret_material(
        legacy_path,
        master_key=derived_legacy_key,
    )
    assert migrated_format == "encrypted"
    assert migrated_secret == original_secret
    try:
        load_wallet_secret_material(legacy_path, master_key=raw_master_key)
    except WalletBackendError:
        pass
    else:
        raise AssertionError("Raw master key unexpectedly decrypted a derived-key wallet")

    alice = ensure_user_solana_wallet("alice@example.com", network="devnet")
    bob = ensure_user_solana_wallet("bob@example.com", network="devnet")
    alice_info = get_user_wallet_storage_info("alice@example.com", network="devnet")
    bob_info = get_user_wallet_storage_info("bob@example.com", network="devnet")
    assert alice["key_scope"] == "per-user-derived"
    assert bob["key_scope"] == "per-user-derived"
    assert alice_info["key_scope"] == "per-user-derived"
    assert bob_info["key_scope"] == "per-user-derived"

    alice_key = _derive_user_scoped_key(raw_master_key, user_id="alice@example.com", network="devnet")
    bob_key = _derive_user_scoped_key(raw_master_key, user_id="bob@example.com", network="devnet")
    assert alice_key != bob_key

    alice_secret, _ = load_wallet_secret_material(Path(alice["path"]), master_key=alice_key)
    bob_secret, _ = load_wallet_secret_material(Path(bob["path"]), master_key=bob_key)
    assert alice_secret != bob_secret

    try:
        load_wallet_secret_material(Path(alice["path"]), master_key=raw_master_key)
    except WalletBackendError:
        pass
    else:
        raise AssertionError("Raw master key unexpectedly decrypted alice wallet")

    print("smoke_user_wallet_key_derivation: ok")


if __name__ == "__main__":
    main()
