"""Smoke test for boot-key backed sealed secret storage."""

from __future__ import annotations

import os
import shutil
import stat
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agent_wallet.bootstrap import generate_solana_wallet_material  # noqa: E402
from agent_wallet.config import (  # noqa: E402
    resolve_approval_secret,
    resolve_solana_private_key,
    resolve_wallet_master_key,
    settings,
)
from agent_wallet.sealed_keys import resolve_sealed_keys_path, seal_keys  # noqa: E402
from agent_wallet.wallet_layer.base import WalletBackendError  # noqa: E402
from agent_wallet.wallet_layer.factory import create_wallet_backend  # noqa: E402


def main() -> None:
    temp_home = Path("/tmp/openclaw-sealed-keys-smoke")
    if temp_home.exists():
        shutil.rmtree(temp_home)

    os.environ["OPENCLAW_HOME"] = str(temp_home)
    os.environ["AGENT_WALLET_BOOT_KEY"] = "test-boot-key-for-sealed-keys-smoke"
    os.environ.pop("AGENT_WALLET_MASTER_KEY", None)
    os.environ.pop("AGENT_WALLET_APPROVAL_SECRET", None)
    os.environ.pop("SOLANA_AGENT_PRIVATE_KEY", None)

    material = generate_solana_wallet_material()
    sealed_path = seal_keys(
        os.environ["AGENT_WALLET_BOOT_KEY"],
        {
            "master_key": "sealed-master-key",
            "approval_secret": "sealed-approval-secret",
            "private_key": material["secret_material"],
        },
    )

    assert sealed_path == resolve_sealed_keys_path()
    mode = stat.S_IMODE(sealed_path.stat().st_mode)
    assert mode == 0o600, oct(mode)

    settings.agent_wallet_boot_key = ""

    assert resolve_wallet_master_key() == "sealed-master-key"
    assert resolve_approval_secret() == "sealed-approval-secret"
    assert resolve_solana_private_key().strip() == material["secret_material"].strip()

    os.environ["AGENT_WALLET_MASTER_KEY"] = "direct-master-key"
    os.environ["AGENT_WALLET_APPROVAL_SECRET"] = "direct-approval-secret"
    os.environ["SOLANA_AGENT_PRIVATE_KEY"] = "direct-private-key"
    for resolver in (
        resolve_wallet_master_key,
        resolve_approval_secret,
        resolve_solana_private_key,
    ):
        try:
            resolver()
        except WalletBackendError as exc:
            assert "no longer supported for runtime secret loading" in str(exc)
        else:
            raise AssertionError("Expected legacy runtime env secret to be rejected.")
    os.environ.pop("AGENT_WALLET_MASTER_KEY", None)
    os.environ.pop("AGENT_WALLET_APPROVAL_SECRET", None)
    os.environ.pop("SOLANA_AGENT_PRIVATE_KEY", None)

    settings.agent_wallet_backend = "solana_local"
    settings.agent_wallet_sign_only = True
    settings.solana_network = "devnet"
    settings.solana_rpc_url = ""
    settings.solana_rpc_urls = "https://api.devnet.solana.com"
    settings.solana_commitment = "confirmed"
    settings.solana_agent_public_key = material["address"]
    settings.solana_agent_keypair_path = ""
    settings.solana_auto_create_wallet = False

    backend = create_wallet_backend()
    assert backend is not None
    assert backend.address == material["address"]
    assert backend.signer is not None

    print("smoke_sealed_keys: ok")


if __name__ == "__main__":
    main()
