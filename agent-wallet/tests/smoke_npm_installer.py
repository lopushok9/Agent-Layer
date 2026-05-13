"""Smoke test for the npm CLI installer wrapper."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path


def main() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    package_version = json.loads((repo_root / "package.json").read_text(encoding="utf-8"))["version"]
    temp_root = Path("/tmp/openclaw-npm-installer-smoke")
    if temp_root.exists():
        shutil.rmtree(temp_root)
    temp_root.mkdir(parents=True, exist_ok=True)

    config_path = temp_root / "openclaw.json"
    env_path = temp_root / ".env"
    runtime_base = temp_root / "agent-wallet-runtime"
    runtime_root = runtime_base / "releases" / package_version
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
    assert (runtime_root / ".openclaw" / "extensions" / "pay-bridge").exists()
    assert (runtime_root / "hermes" / "plugins" / "agent_wallet" / "plugin.yaml").exists()
    assert (runtime_root / "agent-wallet" / "scripts" / "manage_openclaw_evm_wallet.py").exists()
    assert (runtime_root / "agent-wallet" / "scripts" / "bootstrap_openclaw_evm.py").exists()
    assert (runtime_root / "agent-wallet" / "scripts" / "setup_evm_wallet.sh").exists()
    hermes_schemas = (runtime_root / "hermes" / "plugins" / "agent_wallet" / "schemas.py").read_text(
        encoding="utf-8"
    )
    assert "agent_wallet_evm_status" in hermes_schemas
    assert "agent_wallet_evm_setup" in hermes_schemas
    assert (runtime_root / "wdk-btc-wallet" / "package.json").exists()
    assert (runtime_root / "wdk-evm-wallet" / "package.json").exists()
    assert (runtime_base / "current").is_symlink()
    assert (runtime_base / "current").resolve() == runtime_root.resolve()

    fake_bin = temp_root / "fake-bin"
    fake_bin.mkdir(parents=True, exist_ok=True)
    fake_hermes = fake_bin / "hermes"
    fake_hermes.write_text(
        "#!/bin/sh\n"
        "echo \"$@\" >> \"$OPENCLAW_HOME/hermes-calls.log\"\n"
        "exit 0\n",
        encoding="utf-8",
    )
    fake_hermes.chmod(0o755)
    hermes_home = temp_root / "hermes-home"
    hermes_env = dict(env)
    hermes_env["PATH"] = f"{fake_bin}{os.pathsep}{env.get('PATH', '')}"
    hermes_env["HERMES_HOME"] = str(hermes_home)
    hermes_result = subprocess.run(
        ["node", str(cli), "hermes", "install", "--yes"],
        capture_output=True,
        text=True,
        check=True,
        env=hermes_env,
    )
    hermes_payload = json.loads(hermes_result.stdout)
    assert hermes_payload["ok"] is True
    assert Path(hermes_payload["plugin_target"]).is_symlink()
    assert Path(hermes_payload["plugin_target"]).resolve() == (
        runtime_root / "hermes" / "plugins" / "agent_wallet"
    ).resolve()
    assert Path(hermes_payload["agent_wallet_package_root"]).resolve() == (runtime_root / "agent-wallet").resolve()
    assert Path(hermes_payload["boot_key_file"]).read_text(encoding="utf-8").strip() == env["AGENT_WALLET_BOOT_KEY"]
    hermes_env_file = (hermes_home / ".env").read_text(encoding="utf-8")
    assert f"AGENT_WALLET_PACKAGE_ROOT={runtime_root / 'agent-wallet'}" in hermes_env_file
    assert f"AGENT_WALLET_BOOT_KEY_FILE={hermes_payload['boot_key_file']}" in hermes_env_file
    assert (temp_root / "hermes-calls.log").read_text(encoding="utf-8").strip() == "plugins enable agent-wallet"

    status = subprocess.run(
        ["node", str(cli), "status"],
        capture_output=True,
        text=True,
        check=True,
        env=env,
    )
    status_payload = json.loads(status.stdout)
    assert status_payload["active_version"] == package_version
    assert status_payload["available_releases"] == [package_version]

    current_directory_runtime = temp_root / "directory-current-runtime"
    shutil.copytree(runtime_root, current_directory_runtime)
    current_link = runtime_base / "current"
    current_link.unlink()
    shutil.copytree(current_directory_runtime, current_link)
    hermes_result_from_directory_current = subprocess.run(
        ["node", str(cli), "hermes", "install", "--yes", "--force"],
        capture_output=True,
        text=True,
        check=True,
        env=hermes_env,
    )
    directory_current_payload = json.loads(hermes_result_from_directory_current.stdout)
    assert Path(directory_current_payload["agent_wallet_package_root"]).resolve() == (
        current_link / "agent-wallet"
    ).resolve()
    shutil.rmtree(current_link)
    current_link.symlink_to(runtime_root, target_is_directory=True)

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
