"""Smoke test: runtime restarts a healthy same-version daemon from the wrong home.

A stray local daemon can survive on the shared localhost port after a temp-home
install/update and answer /health successfully, but with a different dataDir and
therefore a different bearer token. The runtime must treat that as stale and
restart it before issuing authenticated requests.
"""

from __future__ import annotations

import json
import os
import shutil
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path
from urllib.request import urlopen

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from _secret_test_utils import install_test_sealed_secrets  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
RUNNER = ROOT / "tests" / "_fake_wdk_evm_service_runner.py"


def _health(service_url: str) -> dict | None:
    try:
        with urlopen(f"{service_url}/health", timeout=1.0) as response:
            if int(getattr(response, "status", 0) or 0) != 200:
                return None
            return json.loads(response.read().decode("utf-8"))
    except Exception:
        return None


def _wait_health(service_url: str, *, timeout: float = 10.0) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        payload = _health(service_url)
        if payload is not None:
            return payload
        time.sleep(0.2)
    raise AssertionError(f"service never became healthy at {service_url}")


def main() -> None:
    temp_home = Path("/tmp/openclaw-evm-runtime-restart-wrong-home-smoke")
    if temp_home.exists():
        shutil.rmtree(temp_home)
    wrong_home = temp_home / "wrong-home"
    wrong_home.mkdir(parents=True, exist_ok=True)
    install_test_sealed_secrets(
        temp_home,
        boot_key="runtime-evm-restart-wrong-home-boot-key",
        evm_wallet_password="runtime-evm-restart-wrong-home-password",
    )

    fake_root = temp_home / "fake-wdk-evm-wallet"
    fake_root.mkdir(parents=True, exist_ok=True)
    (fake_root / "package.json").write_text(
        json.dumps({"name": "wdk-evm-wallet", "version": "9.9.9"}) + "\n",
        encoding="utf-8",
    )
    run_local = fake_root / "run-local.sh"
    run_local.write_text(
        "#!/bin/sh\nexec " + sys.executable + " " + str(RUNNER) + "\n",
        encoding="utf-8",
    )
    run_local.chmod(0o755)

    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        free_port = sock.getsockname()[1]
    service_url = f"http://127.0.0.1:{free_port}"

    base_env = os.environ.copy()
    base_env["OPENCLAW_HOME"] = str(temp_home)
    base_env["OPENCLAW_EVM_WDK_WALLET_ROOT"] = str(fake_root)
    base_env["AGENT_WALLET_BACKEND"] = "wdk_evm_local"
    base_env["WDK_EVM_SERVICE_URL"] = service_url
    base_env["WDK_EVM_LOCAL_TOKEN"] = "expected-local-evm-token"
    base_env["WDK_EVM_ACCOUNT_INDEX"] = "0"
    base_env["SOLANA_NETWORK"] = "base"

    stale_env = base_env.copy()
    stale_env["HOST"] = "127.0.0.1"
    stale_env["PORT"] = str(free_port)
    stale_env["OPENCLAW_HOME"] = str(wrong_home)
    stale_env["WDK_EVM_LOCAL_TOKEN"] = "wrong-local-evm-token"
    stale_proc = subprocess.Popen(
        [sys.executable, str(RUNNER)],
        cwd=str(fake_root),
        env=stale_env,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )

    new_pids: list[int] = []
    original_env = os.environ.copy()
    try:
        health = _wait_health(service_url)
        assert health.get("version") == "9.9.9", health
        assert health.get("dataDir") == str(wrong_home / "wdk-evm-wallet"), health

        os.environ.clear()
        os.environ.update(base_env)

        from agent_wallet.config import reload_settings  # noqa: E402
        from agent_wallet.evm_user_wallets import _listening_pids, get_user_evm_wallet_binding  # noqa: E402
        from agent_wallet.openclaw_runtime import onboard_openclaw_user_wallet  # noqa: E402

        reload_settings()
        context = onboard_openclaw_user_wallet(
            "restart-wrong-home@example.com",
            backend="wdk_evm_local",
            network="base",
        )
        session = context.session_metadata()
        assert session.backend == "wdk_evm_local"
        assert session.network == "base"
        assert session.address.startswith("0x")

        binding = get_user_evm_wallet_binding("restart-wrong-home@example.com", network="base")
        assert binding["wallet_id"] == "evm-wallet-123"

        assert stale_proc.poll() is not None, "stale daemon should have been stopped"
        fresh_health = _wait_health(service_url)
        assert fresh_health.get("dataDir") == str(temp_home / "wdk-evm-wallet"), fresh_health
        new_pids = [pid for pid in _listening_pids(free_port) if pid != stale_proc.pid]
        assert new_pids, "fresh daemon should be listening after restart"
    finally:
        os.environ.clear()
        os.environ.update(original_env)
        for pid in new_pids:
            try:
                os.kill(pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
        try:
            os.kill(stale_proc.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass

    print("smoke_openclaw_evm_runtime_restart_wrong_home: ok")


if __name__ == "__main__":
    main()
