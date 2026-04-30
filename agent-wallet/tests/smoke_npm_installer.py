"""Smoke test for the npm CLI installer wrapper."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path


def main() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    temp_root = Path("/tmp/openclaw-npm-installer-smoke")
    if temp_root.exists():
        shutil.rmtree(temp_root)
    temp_root.mkdir(parents=True, exist_ok=True)

    config_path = temp_root / "openclaw.json"
    env_path = temp_root / ".env"
    runtime_base = temp_root / "agent-wallet-runtime"
    runtime_root = runtime_base / "releases" / "0.1.0"
    cli = repo_root / "bin" / "openclaw-agent-wallet.mjs"

    env = dict(os.environ)
    env["OPENCLAW_HOME"] = str(temp_root)
    env["AGENT_WALLET_BOOT_KEY"] = "test-boot-key-for-npm-installer"
    env["AGENT_WALLET_MASTER_KEY"] = "test-master-key-for-npm-installer"
    env["AGENT_WALLET_APPROVAL_SECRET"] = "test-approval-secret-for-npm-installer"

    doctor = subprocess.run(
        ["node", str(cli), "doctor"],
        capture_output=True,
        text=True,
        check=True,
        env=env,
    )
    doctor_payload = json.loads(doctor.stdout)
    assert doctor_payload["ok"] is True
    assert Path(doctor_payload["setup_path"]).resolve() == repo_root / "setup.sh"

    result = subprocess.run(
        [
            "node",
            str(cli),
            "install",
            "--yes",
            "--config-path",
            str(config_path),
            "--env-path",
            str(env_path),
            "--backend",
            "none",
            "--skip-python-setup",
            "--skip-node-setup",
        ],
        capture_output=True,
        text=True,
        check=True,
        env=env,
    )
    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    assert payload["configured"] is False
    assert payload["node_runtime"]["skipped"] is True
    assert Path(payload["runtime_root"]).resolve() == runtime_root.resolve()
    assert (runtime_root / "setup.sh").exists()
    assert (runtime_root / "agent-wallet").exists()
    assert (runtime_root / ".openclaw" / "extensions" / "agent-wallet").exists()
    assert (runtime_root / "wdk-btc-wallet" / "package.json").exists()
    assert (runtime_root / "wdk-evm-wallet" / "package.json").exists()
    assert (runtime_base / "current").is_symlink()
    assert (runtime_base / "current").resolve() == runtime_root.resolve()

    status = subprocess.run(
        ["node", str(cli), "status"],
        capture_output=True,
        text=True,
        check=True,
        env=env,
    )
    status_payload = json.loads(status.stdout)
    assert status_payload["active_version"] == "0.1.0"
    assert status_payload["available_releases"] == ["0.1.0"]

    other_runtime = runtime_base / "releases" / "0.0.9"
    other_runtime.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["node", str(cli), "rollback", "--to", "0.0.9"],
        capture_output=True,
        text=True,
        check=True,
        env=env,
    )
    assert (runtime_base / "current").resolve() == other_runtime.resolve()

    print("smoke_npm_installer: ok")


if __name__ == "__main__":
    main()
