"""Smoke test for host-side OpenClaw EVM wallet onboarding flow."""

from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from _wdk_evm_test_server import FakeWdkEvmWalletServer  # noqa: E402


def main() -> None:
    temp_home = Path("/tmp/openclaw-evm-runtime-smoke")
    if temp_home.exists():
        import shutil

        shutil.rmtree(temp_home)
    os.environ["OPENCLAW_HOME"] = str(temp_home)
    os.environ["OPENCLAW_EVM_WDK_WALLET_ROOT"] = str(Path(__file__).resolve().parents[2] / "wdk-evm-wallet")

    with FakeWdkEvmWalletServer(network="base-sepolia") as server:
        os.environ["AGENT_WALLET_BACKEND"] = "wdk_evm_local"
        os.environ["WDK_EVM_SERVICE_URL"] = server.base_url
        os.environ["WDK_EVM_LOCAL_TOKEN"] = server.auth_token
        os.environ.pop("WDK_EVM_WALLET_ID", None)
        os.environ["WDK_EVM_ACCOUNT_INDEX"] = "0"
        os.environ["SOLANA_NETWORK"] = "sepolia"

        from _secret_test_utils import install_test_sealed_secrets  # noqa: E402
        from agent_wallet.evm_user_wallets import (  # noqa: E402
            create_user_evm_wallet,
            get_user_evm_wallet_binding,
            resolve_user_evm_wallet_path,
        )
        from agent_wallet.openclaw_runtime import onboard_openclaw_user_wallet  # noqa: E402

        install_test_sealed_secrets(
            temp_home,
            boot_key="runtime-evm-boot-key",
            evm_wallet_password="runtime-evm-password",
        )
        created = create_user_evm_wallet(
            "runtime-evm@example.com",
            password="runtime-evm-password",
            network="sepolia",
            service_url=server.base_url,
        )
        assert created["wallet_id"] == server.wallet_id

        server.unlocked_wallet_ids.clear()

        context = onboard_openclaw_user_wallet("runtime-evm@example.com", network="sepolia")
        session = context.session_metadata()
        bundle = context.serializable_bundle()

        assert context.created_now is False
        assert session.chain == "evm"
        assert session.backend == "wdk_evm_local"
        assert session.network == "sepolia"
        assert session.storage_format == "local_vault"
        assert session.address.startswith("0x")
        assert "get_evm_token_metadata" in session.tool_names
        assert "get_evm_swap_quote" not in session.tool_names
        assert "swap_evm_tokens" not in session.tool_names
        assert "transfer_evm_native" in session.tool_names
        assert "transfer_sol" not in session.tool_names
        assert bundle["session"]["address"] == session.address
        assert server.wallet_id in server.unlocked_wallet_ids

        autobind_user = "runtime-evm-autobind@example.com"
        created_autobind = create_user_evm_wallet(
            autobind_user,
            password="runtime-evm-password",
            network="sepolia",
            service_url=server.base_url,
        )
        assert created_autobind["wallet_id"] == server.wallet_id
        assert resolve_user_evm_wallet_path(autobind_user, network="base-sepolia").exists() is False

        autobind_context = onboard_openclaw_user_wallet(autobind_user, network="base-sepolia")
        autobind_session = autobind_context.session_metadata()
        autobind_binding = get_user_evm_wallet_binding(autobind_user, network="base-sepolia")

        assert autobind_session.network == "base-sepolia"
        assert "get_evm_token_metadata" in autobind_session.tool_names
        assert "get_evm_swap_quote" not in autobind_session.tool_names
        assert "swap_evm_tokens" not in autobind_session.tool_names
        assert autobind_binding["wallet_id"] == created_autobind["wallet_id"]
        assert autobind_binding["address"] == created_autobind["address"]
        assert resolve_user_evm_wallet_path(autobind_user, network="base-sepolia").exists() is True

        autoprovision_user = "runtime-evm-autoprovision@example.com"
        autoprovision_context = onboard_openclaw_user_wallet(autoprovision_user, network="base")
        autoprovision_session = autoprovision_context.session_metadata()
        autoprovision_binding = get_user_evm_wallet_binding(autoprovision_user, network="base")

        assert autoprovision_session.network == "base"
        assert autoprovision_binding["wallet_id"] == server.wallet_id
        assert resolve_user_evm_wallet_path(autoprovision_user, network="ethereum").exists() is True

    print("smoke_openclaw_evm_runtime: ok")


if __name__ == "__main__":
    main()
