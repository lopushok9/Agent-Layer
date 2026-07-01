"""Smoke test: read-only onboarding must not decrypt the wallet secret once pinned."""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from _secret_test_utils import install_test_sealed_secrets  # noqa: E402

import agent_wallet.user_wallets as user_wallets  # noqa: E402
from agent_wallet.openclaw_runtime import onboard_openclaw_user_wallet  # noqa: E402


def main() -> None:
    temp_home = Path("/tmp/openclaw-read-only-wallet-no-decrypt-smoke")
    if temp_home.exists():
        shutil.rmtree(temp_home)
    install_test_sealed_secrets(
        temp_home,
        boot_key="test-boot-key-for-read-only-no-decrypt-smoke",
        master_key="test-master-key-for-read-only-no-decrypt-smoke",
    )
    os.environ["AGENT_WALLET_MIGRATE_PLAINTEXT_USER_WALLETS"] = "true"

    user_id = "read-only-no-decrypt@example.com"

    # First call provisions the wallet + pin file from scratch; decrypting the
    # secret material here is unavoidable and expected.
    first = onboard_openclaw_user_wallet(user_id, network="mainnet", read_only=True)
    assert first.created_now is True
    assert first.wallet_info["address"]

    # Second call must resolve the address purely from the plaintext pin file
    # and must never touch the encrypted secret material or derive a signer.
    original_load_secret = user_wallets._load_user_wallet_secret_material

    def _forbidden_decrypt(*args, **kwargs):
        raise AssertionError(
            "read-only onboarding decrypted wallet secret material after the "
            "wallet was already pinned"
        )

    user_wallets._load_user_wallet_secret_material = _forbidden_decrypt
    try:
        second = onboard_openclaw_user_wallet(user_id, network="mainnet", read_only=True)
    finally:
        user_wallets._load_user_wallet_secret_material = original_load_secret

    assert second.created_now is False
    assert second.wallet_info["address"] == first.wallet_info["address"]
    assert second.wallet_info["key_scope"] == "pinned-address-only"
    assert second.backend.signer is None
    assert second.backend.address == first.wallet_info["address"]

    print("smoke_read_only_wallet_no_decrypt: ok")


if __name__ == "__main__":
    main()
