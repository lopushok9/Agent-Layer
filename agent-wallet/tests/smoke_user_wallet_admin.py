"""Smoke test for user wallet backup export and encryption rotation."""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from _secret_test_utils import install_test_sealed_secrets  # noqa: E402
from agent_wallet.encrypted_storage import (  # noqa: E402
    _derive_user_scoped_key,
    decrypt_secret_material,
    load_wallet_secret_material,
)
from agent_wallet.user_wallets import (  # noqa: E402
    ensure_user_solana_wallet,
    export_user_wallet_backup,
    get_user_wallet_storage_info,
    resolve_user_wallet_path,
    rotate_user_wallet_encryption,
)
from agent_wallet.wallet_layer.base import WalletBackendError  # noqa: E402


def main() -> None:
    temp_home = Path("/tmp/openclaw-user-wallet-admin-smoke")
    if temp_home.exists():
        shutil.rmtree(temp_home)
    install_test_sealed_secrets(
        temp_home,
        boot_key="test-boot-key-for-user-wallet-admin-smoke",
        master_key="test-master-key-one",
    )
    os.environ["AGENT_WALLET_MIGRATE_PLAINTEXT_USER_WALLETS"] = "true"

    first_master_key = "test-master-key-one"
    second_master_key = "test-master-key-two"
    backup_master_key = "test-backup-master-key"

    created = ensure_user_solana_wallet("ops@example.com", network="devnet")
    path = resolve_user_wallet_path("ops@example.com", network="devnet")

    info = get_user_wallet_storage_info("ops@example.com", network="devnet")
    assert info["storage_format"] == "encrypted"
    assert info["address"] == created["address"]

    first_derived_key = _derive_user_scoped_key(
        first_master_key,
        user_id="ops@example.com",
        network="devnet",
    )
    original_secret, original_format = load_wallet_secret_material(path, master_key=first_derived_key)
    assert original_format == "encrypted"

    backup = export_user_wallet_backup(
        "ops@example.com",
        network="devnet",
        current_master_key=first_master_key,
        export_master_key=backup_master_key,
    )
    exported_secret = decrypt_secret_material(
        backup["backup_payload"],
        master_key=backup_master_key,
    )
    assert exported_secret == original_secret

    rotated = rotate_user_wallet_encryption(
        "ops@example.com",
        network="devnet",
        current_master_key=first_master_key,
        new_master_key=second_master_key,
    )
    assert rotated["storage_format"] == "encrypted"

    try:
        load_wallet_secret_material(path, master_key=first_master_key)
    except WalletBackendError:
        pass
    else:
        raise AssertionError("Old master key unexpectedly decrypted the rotated wallet")

    second_derived_key = _derive_user_scoped_key(
        second_master_key,
        user_id="ops@example.com",
        network="devnet",
    )
    rotated_secret, rotated_format = load_wallet_secret_material(path, master_key=second_derived_key)
    assert rotated_format == "encrypted"
    assert rotated_secret == original_secret

    print("smoke_user_wallet_admin: ok")


if __name__ == "__main__":
    main()
