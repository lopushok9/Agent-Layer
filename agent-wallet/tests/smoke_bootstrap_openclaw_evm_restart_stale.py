"""Smoke test: bootstrap restarts a running-but-stale local WDK EVM daemon.

A long-running daemon serves the code it loaded at boot. After a release the
on-disk launcher version moves ahead of the running process; the host autostart
must detect the version drift via /health and restart the daemon so the new code
takes effect.
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
SCRIPT = ROOT / "scripts" / "bootstrap_openclaw_evm.py"
RUNNER = ROOT / "tests" / "_fake_wdk_evm_service_runner.py"

ON_DISK_VERSION = "9.9.9"
STALE_VERSION = "0.0.0-stale"


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
    temp_home = Path("/tmp/openclaw-evm-bootstrap-restart-stale-smoke")
    if temp_home.exists():
        shutil.rmtree(temp_home)
    install_test_sealed_secrets(
        temp_home,
        boot_key="test-boot-key-for-evm-bootstrap-restart-stale-smoke",
        master_key="test-master-key-for-evm-bootstrap-restart-stale-smoke",
        approval_secret="test-approval-secret-for-evm-bootstrap-restart-stale-smoke",
    )

    fake_root = temp_home / "fake-wdk-evm-wallet"
    fake_root.mkdir(parents=True, exist_ok=True)
    run_local = fake_root / "run-local.sh"
    run_local.write_text(
        "#!/bin/sh\nexec " + sys.executable + " " + str(RUNNER) + "\n",
        encoding="utf-8",
    )
    run_local.chmod(0o755)
    # On-disk launcher version the restarted daemon will report.
    (fake_root / "package.json").write_text(
        json.dumps({"name": "wdk-evm-wallet", "version": ON_DISK_VERSION}) + "\n",
        encoding="utf-8",
    )

    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        free_port = sock.getsockname()[1]
    service_url = f"http://127.0.0.1:{free_port}"

    base_env = os.environ.copy()
    base_env["PYTHONPATH"] = str(ROOT)
    base_env["WDK_EVM_LOCAL_TOKEN"] = "test-local-evm-token"

    # Pre-start a STALE daemon already listening on the port.
    stale_env = base_env.copy()
    stale_env["HOST"] = "127.0.0.1"
    stale_env["PORT"] = str(free_port)
    stale_env["WDK_EVM_FAKE_VERSION"] = STALE_VERSION
    stale_proc = subprocess.Popen(
        [sys.executable, str(RUNNER)],
        cwd=str(fake_root),
        env=stale_env,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    new_pid: int | None = None
    try:
        health = _wait_health(service_url)
        assert health.get("version") == STALE_VERSION, health

        config_path = temp_home / "openclaw.json"
        completed = subprocess.run(
            [
                sys.executable,
                str(SCRIPT),
                "--config-path",
                str(config_path),
                "--user-id",
                "bootstrap-evm-restart-stale@example.com",
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
            env=base_env,
            input="bootstrap-evm-restart-stale-password\n",
        )
        payload = json.loads(completed.stdout)
        service_bootstrap = payload["service_bootstrap"]

        assert payload["ok"] is True, payload
        assert service_bootstrap["restarted"] is True, service_bootstrap
        assert service_bootstrap["started"] is True, service_bootstrap
        new_pid = int(service_bootstrap["pid"])

        # The stale daemon was stopped, and the fresh one reports the on-disk version.
        assert stale_proc.poll() is not None, "stale daemon should have been stopped"
        fresh_health = _wait_health(service_url)
        assert fresh_health.get("version") == ON_DISK_VERSION, fresh_health
    finally:
        for pid in (new_pid, stale_proc.pid):
            if pid is None:
                continue
            try:
                os.kill(pid, signal.SIGTERM)
            except ProcessLookupError:
                pass

    print("smoke_bootstrap_openclaw_evm_restart_stale: ok")


if __name__ == "__main__":
    main()
