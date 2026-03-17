"""Smoke test for encrypted wallet secret storage helpers."""

from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agent_wallet.encrypted_storage import (  # noqa: E402
    _derive_user_scoped_key,
    decrypt_secret_material,
    encrypt_secret_material,
    is_encrypted_wallet_payload,
    load_wallet_secret_material,
    write_encrypted_wallet_file,
)


def main() -> None:
    os.environ["AGENT_WALLET_MASTER_KEY"] = "test-master-key-for-smoke-encrypted-storage"
    secret_material = "[1, 2, 3, 4]"

    encrypted = encrypt_secret_material(
        secret_material,
        metadata={"address": "test-address"},
    )
    assert is_encrypted_wallet_payload(encrypted)
    assert decrypt_secret_material(encrypted) == secret_material
    derived_alice = _derive_user_scoped_key(
        os.environ["AGENT_WALLET_MASTER_KEY"],
        user_id="alice@example.com",
        network="devnet",
    )
    derived_bob = _derive_user_scoped_key(
        os.environ["AGENT_WALLET_MASTER_KEY"],
        user_id="bob@example.com",
        network="devnet",
    )
    assert derived_alice != derived_bob
    assert derived_alice == _derive_user_scoped_key(
        os.environ["AGENT_WALLET_MASTER_KEY"],
        user_id="alice@example.com",
        network="devnet",
    )

    path = Path("/tmp/openclaw-encrypted-wallet-smoke.json")
    write_encrypted_wallet_file(path, secret_material, metadata={"network": "devnet"})
    loaded, storage_format = load_wallet_secret_material(path)
    assert loaded == secret_material
    assert storage_format == "encrypted"

    print("smoke_encrypted_storage: ok")


if __name__ == "__main__":
    main()
