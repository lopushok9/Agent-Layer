"""Smoke test for auto-starting the local WDK EVM service during bootstrap."""

from __future__ import annotations

import json
import os
import shutil
import signal
import socket
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from _secret_test_utils import install_test_sealed_secrets  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "bootstrap_openclaw_evm.py"
RUNNER = ROOT / "tests" / "_fake_wdk_evm_service_runner.py"


def main() -> None:
    temp_home = Path("/tmp/openclaw-evm-bootstrap-autostart-smoke")
    if temp_home.exists():
        shutil.rmtree(temp_home)
    install_test_sealed_secrets(
        temp_home,
        boot_key="test-boot-key-for-evm-bootstrap-autostart-smoke",
        master_key="test-master-key-for-evm-bootstrap-autostart-smoke",
        approval_secret="test-approval-secret-for-evm-bootstrap-autostart-smoke",
    )

    fake_root = temp_home / "fake-wdk-evm-wallet"
    fake_root.mkdir(parents=True, exist_ok=True)
    run_local = fake_root / "run-local.sh"
    run_local.write_text(
        "#!/bin/sh\n"
        "exec "
        + sys.executable
        + " "
        + str(RUNNER)
        + "\n",
        encoding="utf-8",
    )
    run_local.chmod(0o755)
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        free_port = sock.getsockname()[1]
    service_url = f"http://127.0.0.1:{free_port}"

    config_path = temp_home / "openclaw.json"
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT)
    env["WDK_EVM_LOCAL_TOKEN"] = "test-local-evm-token"
    completed = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--config-path",
            str(config_path),
            "--user-id",
            "bootstrap-evm-autostart@example.com",
            "--network",
            "base",
            "--service-url",
            service_url,
            "--wdk-wallet-root",
            str(fake_root),
            "--password-stdin",
        ],
        check=True,
        capture_output=True,
        text=True,
        env=env,
        input="bootstrap-evm-autostart-password\n",
    )
    payload = json.loads(completed.stdout)
    pid = int(payload["service_bootstrap"]["pid"])
    try:
        assert payload["ok"] is True
        assert payload["service_bootstrap"]["started"] is True
        assert Path(payload["service_bootstrap"]["log_path"]).exists()
        config = json.loads(config_path.read_text(encoding="utf-8"))
        plugin_config = config["plugins"]["entries"]["agent-wallet"]["config"]
        assert plugin_config["wdkEvmServiceUrl"] == service_url
        assert plugin_config["backend"] == "wdk_evm_local"
    finally:
        os.kill(pid, signal.SIGTERM)

    print("smoke_bootstrap_openclaw_evm_autostart: ok")


if __name__ == "__main__":
    main()
