"""Smoke test: the single-agent factory reuses the local-service recovery
that previously only ran for the multi-user OpenClaw wallet path.

Before this fix, `create_wallet_backend()` handed back a `WdkEvmLocalWalletBackend`
that talked to the wdk-evm-wallet daemon over a bare HTTP client with no
health check, so an unreachable or stale daemon surfaced as an opaque
connection error instead of self-healing. This test verifies the wiring
without starting a real daemon: it stubs
`agent_wallet.evm_user_wallets.ensure_local_evm_service_ready` and asserts
`create_wallet_backend()` calls it with the resolved network for the EVM
backend only, respects the opt-out env var, and lets its errors propagate
rather than swallowing them.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import agent_wallet.evm_user_wallets as evm_user_wallets  # noqa: E402
from agent_wallet.config import settings  # noqa: E402
from agent_wallet.wallet_layer.base import WalletBackendError  # noqa: E402
from agent_wallet.wallet_layer.factory import create_wallet_backend  # noqa: E402
from agent_wallet.wallet_layer.wdk_evm import WdkEvmLocalWalletBackend  # noqa: E402


def main() -> None:
    original_backend = settings.agent_wallet_backend
    original_network = settings.solana_network
    original_service_url = settings.wdk_evm_service_url
    original_wallet_id = settings.wdk_evm_wallet_id
    original_solana_public_key = settings.solana_agent_public_key
    original_autostart_disable = os.environ.get("AGENT_WALLET_EVM_DISABLE_AUTOSTART")
    original_local_token = os.environ.get("WDK_EVM_LOCAL_TOKEN")
    original_ensure = evm_user_wallets.ensure_local_evm_service_ready

    calls: list[tuple[str, str]] = []

    def fake_ensure(service_url: str, network: str) -> None:
        calls.append((service_url, network))

    try:
        os.environ.pop("AGENT_WALLET_EVM_DISABLE_AUTOSTART", None)
        # ensure_local_evm_service_ready is stubbed above -- no real daemon
        # ever starts -- but WdkEvmLocalWalletBackend still eagerly builds a
        # WdkEvmLocalClient, which reads a real local-auth-token file from
        # disk unless this env var is set. A dev machine that has ever run
        # the real daemon has that file already, which let this test pass
        # locally while failing on a fresh checkout with no such file.
        os.environ["WDK_EVM_LOCAL_TOKEN"] = "test-local-evm-token-for-factory-autostart-smoke"
        settings.agent_wallet_backend = "wdk_evm_local"
        settings.solana_network = "base"
        settings.wdk_evm_service_url = "http://127.0.0.1:8081"
        settings.wdk_evm_wallet_id = "test-evm-wallet-id"
        evm_user_wallets.ensure_local_evm_service_ready = fake_ensure

        backend = create_wallet_backend()
        assert isinstance(backend, WdkEvmLocalWalletBackend)
        assert backend.network == "base"
        assert calls == [("http://127.0.0.1:8081", "base")]

        # Opt-out: the escape hatch must skip the recovery call entirely.
        calls.clear()
        os.environ["AGENT_WALLET_EVM_DISABLE_AUTOSTART"] = "1"
        create_wallet_backend()
        assert calls == [], "autostart must be skipped when explicitly disabled"
        os.environ.pop("AGENT_WALLET_EVM_DISABLE_AUTOSTART", None)

        # A recovery failure (e.g. a foreign-home daemon on the port) must
        # surface as a clear error, not be swallowed by the factory.
        def failing_ensure(service_url: str, network: str) -> None:
            raise WalletBackendError("a stale daemon is occupying the port")

        evm_user_wallets.ensure_local_evm_service_ready = failing_ensure
        try:
            create_wallet_backend()
            raise AssertionError("expected WalletBackendError to propagate")
        except WalletBackendError as exc:
            assert "stale daemon" in str(exc)

        # Other backends must never touch the EVM recovery path. Whether the
        # solana_local branch itself fully succeeds in this environment is
        # beside the point here; only that it never calls EVM's recovery.
        calls.clear()
        evm_user_wallets.ensure_local_evm_service_ready = fake_ensure
        settings.agent_wallet_backend = "solana_local"
        settings.solana_network = "mainnet"
        settings.solana_agent_public_key = "11111111111111111111111111111111"
        try:
            create_wallet_backend()
        except WalletBackendError:
            pass
        assert calls == [], "solana_local must not trigger EVM autostart"
    finally:
        settings.agent_wallet_backend = original_backend
        settings.solana_network = original_network
        settings.wdk_evm_service_url = original_service_url
        settings.wdk_evm_wallet_id = original_wallet_id
        settings.solana_agent_public_key = original_solana_public_key
        evm_user_wallets.ensure_local_evm_service_ready = original_ensure
        if original_autostart_disable is None:
            os.environ.pop("AGENT_WALLET_EVM_DISABLE_AUTOSTART", None)
        else:
            os.environ["AGENT_WALLET_EVM_DISABLE_AUTOSTART"] = original_autostart_disable
        if original_local_token is None:
            os.environ.pop("WDK_EVM_LOCAL_TOKEN", None)
        else:
            os.environ["WDK_EVM_LOCAL_TOKEN"] = original_local_token

    print("smoke_wdk_evm_factory_autostart: ok")


if __name__ == "__main__":
    main()
