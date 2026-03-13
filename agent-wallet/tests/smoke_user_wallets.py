"""Smoke test for user-scoped wallet provisioning."""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agent_wallet.bootstrap import create_solana_wallet_file  # noqa: E402
from agent_wallet.encrypted_storage import is_encrypted_wallet_payload  # noqa: E402
from agent_wallet.user_wallets import (  # noqa: E402
    create_wallet_backend_for_user,
    ensure_user_solana_wallet,
    normalize_user_id,
    resolve_user_wallet_path,
)
from agent_wallet.wallet_layer.base import WalletBackendError  # noqa: E402


def main() -> None:
    temp_home = Path("/tmp/openclaw-user-wallet-smoke")
    if temp_home.exists():
        shutil.rmtree(temp_home)
    os.environ["OPENCLAW_HOME"] = str(temp_home)
    os.environ["AGENT_WALLET_MASTER_KEY"] = "test-master-key-for-smoke-user-wallets"
    os.environ["AGENT_WALLET_ENCRYPT_USER_WALLETS"] = "true"
    os.environ["AGENT_WALLET_MIGRATE_PLAINTEXT_USER_WALLETS"] = "true"

    first = ensure_user_solana_wallet("alice@example.com", network="devnet")
    second = ensure_user_solana_wallet("bob@example.com", network="devnet")

    assert first["address"] != second["address"]
    assert Path(first["path"]).exists()
    assert Path(second["path"]).exists()
    assert normalize_user_id("alice@example.com") != normalize_user_id("bob@example.com")
    assert resolve_user_wallet_path("alice@example.com", "devnet") != resolve_user_wallet_path(
        "bob@example.com",
        "devnet",
    )
    assert first["storage_format"] == "encrypted"
    assert second["storage_format"] == "encrypted"
    assert is_encrypted_wallet_payload(Path(first["path"]).read_text(encoding="utf-8"))
    assert is_encrypted_wallet_payload(Path(second["path"]).read_text(encoding="utf-8"))

    backend = create_wallet_backend_for_user("alice@example.com", sign_only=True, network="devnet")
    assert backend.address == first["address"]
    assert backend.sign_only is True
    assert "users" in first["path"]
    assert Path(f"{first['path']}.pin.json").exists()

    legacy_path = resolve_user_wallet_path("legacy@example.com", "devnet")
    legacy = create_solana_wallet_file(legacy_path)
    assert not is_encrypted_wallet_payload(legacy_path.read_text(encoding="utf-8"))

    migrated = ensure_user_solana_wallet("legacy@example.com", network="devnet")
    assert migrated["address"] == legacy["address"]
    assert migrated["storage_format"] == "encrypted"
    assert is_encrypted_wallet_payload(legacy_path.read_text(encoding="utf-8"))

    mainnet = ensure_user_solana_wallet("mainnet@example.com", network="mainnet")
    mainnet_path = Path(mainnet["path"])
    assert Path(f"{mainnet['path']}.pin.json").exists()
    mainnet_path.unlink()
    try:
        ensure_user_solana_wallet("mainnet@example.com", network="mainnet")
    except WalletBackendError as exc:
        assert "Refusing to create a new mainnet wallet" in str(exc)
    else:
        raise AssertionError("Expected mainnet wallet recreation to be refused.")

    print("smoke_user_wallets: ok")


if __name__ == "__main__":
    main()
