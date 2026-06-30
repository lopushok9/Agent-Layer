"""Smoke test for read-only OpenClaw runtime onboarding."""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from _secret_test_utils import install_test_sealed_secrets  # noqa: E402
from agent_wallet.openclaw_runtime import onboard_openclaw_user_wallet  # noqa: E402


def main() -> None:
    temp_home = Path("/tmp/openclaw-runtime-wallet-read-only-smoke")
    if temp_home.exists():
        shutil.rmtree(temp_home)
    install_test_sealed_secrets(
        temp_home,
        boot_key="test-boot-key-for-runtime-read-only-smoke",
        master_key="test-master-key-for-runtime-read-only-smoke",
    )
    os.environ["AGENT_WALLET_MIGRATE_PLAINTEXT_USER_WALLETS"] = "true"

    runtime = onboard_openclaw_user_wallet(
        "runtime-read-only@example.com",
        network="mainnet",
        read_only=True,
    )

    capabilities = runtime.backend.get_capabilities()
    session = runtime.session_metadata()

    assert runtime.created_now is True
    assert capabilities.chain == "solana"
    assert capabilities.custody_model == "read_only"
    assert capabilities.has_signer is False
    assert capabilities.can_sign_message is False
    assert capabilities.can_send_transaction is False
    assert runtime.wallet_info["address"]
    assert runtime.backend.address == runtime.wallet_info["address"]
    assert runtime.backend.signer is None
    assert session.sign_only is True
    assert session.address == runtime.wallet_info["address"]

    print("smoke_openclaw_runtime_read_only: ok")


if __name__ == "__main__":
    main()
