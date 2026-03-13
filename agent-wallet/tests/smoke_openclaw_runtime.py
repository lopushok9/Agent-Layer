"""Smoke test for host-side OpenClaw wallet onboarding flow."""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agent_wallet.openclaw_runtime import onboard_openclaw_user_wallet  # noqa: E402


def main() -> None:
    temp_home = Path("/tmp/openclaw-runtime-wallet-smoke")
    if temp_home.exists():
        shutil.rmtree(temp_home)
    os.environ["OPENCLAW_HOME"] = str(temp_home)
    os.environ["AGENT_WALLET_MASTER_KEY"] = "test-master-key-for-runtime-smoke"
    os.environ["AGENT_WALLET_ENCRYPT_USER_WALLETS"] = "true"
    os.environ["AGENT_WALLET_MIGRATE_PLAINTEXT_USER_WALLETS"] = "true"

    first = onboard_openclaw_user_wallet(
        "runtime-user@example.com",
        network="devnet",
    )
    first_session = first.session_metadata()
    first_bundle = first.serializable_bundle()

    assert first.created_now is True
    assert first_session.user_id == "runtime-user@example.com"
    assert first_session.network == "devnet"
    assert first_session.sign_only is False
    assert first_session.storage_format == "encrypted"
    assert "get_wallet_address" in first_session.tool_names
    assert first_bundle["session"]["created_now"] is True
    assert first_bundle["manifest"]["id"] == "agent-wallet"
    assert callable(first.plugin_bundle["invoke"])

    second = onboard_openclaw_user_wallet(
        "runtime-user@example.com",
        network="devnet",
    )
    second_session = second.session_metadata()

    assert second.created_now is False
    assert second_session.address == first_session.address
    assert second_session.wallet_path == first_session.wallet_path
    assert second_session.storage_format == "encrypted"

    print("smoke_openclaw_runtime: ok")


if __name__ == "__main__":
    main()
