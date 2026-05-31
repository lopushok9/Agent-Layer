"""Smoke test: the installer auto-provisions the EVM wallet (best-effort).

Covers the install-time EVM provisioning added to install_agent_wallet.py:
  - _bootstrap_evm_wallet provisions a wallet against a healthy service and binds
    BOTH base and ethereum (one address);
  - it is best-effort: an unreachable service yields ok=False without raising;
  - the onboard-config builders force the right backend/network ("always both").
"""

from __future__ import annotations

import argparse
import os
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from _secret_test_utils import install_test_sealed_secrets  # noqa: E402
from _wdk_evm_test_server import FakeWdkEvmWalletServer  # noqa: E402

import importlib.util  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
_SPEC = importlib.util.spec_from_file_location(
    "install_agent_wallet", ROOT / "scripts" / "install_agent_wallet.py"
)
installer = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(installer)  # type: ignore[union-attr]

USER_ID = "install-evm-autocreate@example.com"


def _args(*, backend: str, network: str, service_url: str) -> argparse.Namespace:
    return argparse.Namespace(
        user_id=USER_ID,
        backend=backend,
        network=network,
        sign_only=False,
        rpc_url="",
        rpc_urls="",
        wdk_evm_service_url=service_url,
    )


def _wallets_dir(home: Path) -> Path:
    base = home / "users"
    matches = list(base.glob("*/wallets"))
    return matches[0] if matches else base / "missing" / "wallets"


def main() -> None:
    # --- Pure builder behavior (no network) -------------------------------------
    assert installer._is_evm_backend("wdk_evm_local")
    assert not installer._is_evm_backend("solana_local")

    # EVM active -> uses the chosen network; non-EVM active -> seeds with "base".
    cfg_evm = installer._build_evm_onboard_config(
        _args(backend="wdk_evm_local", network="ethereum", service_url="http://127.0.0.1:8081")
    )
    assert cfg_evm["backend"] == "wdk_evm_local"
    assert cfg_evm["network"] == "ethereum"
    cfg_seed = installer._build_evm_onboard_config(
        _args(backend="solana_local", network="mainnet", service_url="http://127.0.0.1:8081")
    )
    assert cfg_seed["network"] == "base", "non-EVM active install should seed EVM creation with base"

    # Solana is always provisioned: backend/network forced regardless of active backend.
    sol_cfg = installer._build_solana_onboard_config(
        _args(backend="wdk_evm_local", network="base", service_url="http://127.0.0.1:8081")
    )
    assert sol_cfg["backend"] == "solana_local"
    assert sol_cfg["network"] == "mainnet"
    assert "rpcUrl" not in sol_cfg  # EVM-active install must not leak an EVM rpc into solana onboard

    # _build_next_steps only threads the EVM service URL for an EVM-active install.
    common = dict(
        package_root=ROOT,
        extension_path=ROOT,
    )
    evm_steps = installer._build_next_steps(
        Path(sys.executable),
        ROOT / "scripts" / "install_openclaw_local_config.py",
        argparse.Namespace(
            **_args(backend="wdk_evm_local", network="base", service_url="http://127.0.0.1:9999").__dict__,
            plugin_id="agent-wallet",
            config_path="/tmp/x.json",
        ),
        **common,
    )
    assert "--wdk-evm-service-url" in evm_steps and "http://127.0.0.1:9999" in evm_steps

    # --- Success path: provision against a healthy fake service -----------------
    temp_home = Path("/tmp/openclaw-install-evm-autocreate")
    if temp_home.exists():
        shutil.rmtree(temp_home)
    install_test_sealed_secrets(
        temp_home,
        boot_key="test-boot-key-install-evm-autocreate",
        master_key="test-master-key-install-evm-autocreate",
        approval_secret="test-approval-secret-install-evm-autocreate",
        # NOTE: no evm_wallet_password -> exercises auto-generation + sealing.
    )

    with FakeWdkEvmWalletServer(network="base", start_empty=True) as server:
        os.environ["WDK_EVM_LOCAL_TOKEN"] = server.auth_token
        result = installer._bootstrap_evm_wallet(
            Path(sys.executable),
            ROOT,
            _args(backend="solana_local", network="mainnet", service_url=server.base_url),
            ROOT / "wdk-evm-wallet",
        )

    assert result.get("ok") is True, f"EVM provisioning should succeed: {result.get('error')}"
    assert result.get("address"), "provisioning should return an address"
    assert result.get("networks") == ["base", "ethereum"]

    wallets_dir = _wallets_dir(temp_home)
    base_binding = wallets_dir / "evm-base-agent.json"
    eth_binding = wallets_dir / "evm-ethereum-agent.json"
    assert base_binding.exists(), f"missing base binding: {base_binding}"
    assert eth_binding.exists(), f"missing ethereum binding (pair): {eth_binding}"

    # The sealed EVM password was auto-generated and stored under the boot key.
    from agent_wallet.config import resolve_evm_wallet_password

    assert resolve_evm_wallet_password(), "EVM wallet password should have been generated and sealed"

    # --- Best-effort: unreachable service must not raise ------------------------
    # Non-local, unroutable host (TEST-NET-3): provisioning fails deterministically
    # without spawning a real Node service.
    dead = installer._bootstrap_evm_wallet(
        Path(sys.executable),
        ROOT,
        _args(backend="solana_local", network="mainnet", service_url="http://203.0.113.1:8081"),
        ROOT / "wdk-evm-wallet",
    )
    assert dead.get("ok") is False, "unreachable EVM service should yield ok=False"
    assert dead.get("error"), "failure result should carry an error detail"

    shutil.rmtree(temp_home, ignore_errors=True)
    print("smoke_install_evm_autocreate: ok")


if __name__ == "__main__":
    main()
