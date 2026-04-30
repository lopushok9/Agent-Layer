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
    runtime_root = temp_root / "agent-wallet-runtime" / "current"
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
            "--config-path",
            str(config_path),
            "--env-path",
            str(env_path),
            "--runtime-root",
            str(runtime_root),
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

    print("smoke_npm_installer: ok")


if __name__ == "__main__":
    main()
