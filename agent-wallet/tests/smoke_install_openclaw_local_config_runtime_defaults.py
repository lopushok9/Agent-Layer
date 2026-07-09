"""Smoke test for trusted runtime defaults in install_openclaw_local_config.py."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path


def main() -> None:
    temp_root = Path("/tmp/openclaw-install-config-runtime-defaults-smoke")
    if temp_root.exists():
        shutil.rmtree(temp_root)
    temp_root.mkdir(parents=True, exist_ok=True)

    release_root = temp_root / "agent-wallet-runtime" / "releases" / "9.9.9"
    runtime_root = temp_root / "agent-wallet-runtime" / "current"
    runtime_extension = release_root / ".openclaw" / "extensions" / "agent-wallet"
    runtime_package = release_root / "agent-wallet"
    runtime_venv_bin = runtime_package / ".runtime-venv" / "bin"
    runtime_extension.mkdir(parents=True, exist_ok=True)
    runtime_package.mkdir(parents=True, exist_ok=True)
    runtime_venv_bin.mkdir(parents=True, exist_ok=True)
    runtime_root.parent.mkdir(parents=True, exist_ok=True)
    runtime_root.symlink_to(release_root)

    (runtime_extension / "openclaw.plugin.json").write_text('{"id":"agent-wallet"}\n', encoding="utf-8")
    wrapper = runtime_venv_bin / "openclaw-agent-wallet-python"
    wrapper.write_text('#!/bin/sh\nexec "$(dirname "$0")/python" "$@"\n', encoding="utf-8")
    wrapper.chmod(0o755)

    config_path = temp_root / "openclaw.json"
    config_path.write_text(
        json.dumps({"plugins": {"entries": {}}, "tools": {"alsoAllow": []}}, indent=2) + "\n",
        encoding="utf-8",
    )

    env = dict(os.environ)
    env["OPENCLAW_HOME"] = str(temp_root)
    env["AGENT_WALLET_BOOT_KEY"] = "test-boot-key-for-runtime-defaults"
    env["AGENT_WALLET_MASTER_KEY"] = "runtime-defaults-master-key"
    env["AGENT_WALLET_APPROVAL_SECRET"] = "runtime-defaults-approval-secret"

    script = Path(__file__).resolve().parents[1] / "scripts" / "install_openclaw_local_config.py"
    completed = subprocess.run(
        [
            sys.executable,
            str(script),
            "--config-path",
            str(config_path),
            "--extension-path",
            str(runtime_extension),
            "--package-root",
            str(runtime_package),
            "--python-bin",
            str(wrapper),
        ],
        capture_output=True,
        text=True,
        check=True,
        env=env,
    )

    payload = json.loads(completed.stdout)
    assert payload["ok"] is True
    assert payload["extension_path"] == str(runtime_root / ".openclaw" / "extensions" / "agent-wallet")
    assert payload["package_root"] == str(runtime_root / "agent-wallet")
    assert payload["python_bin"] == str(runtime_root / "agent-wallet" / ".runtime-venv" / "bin" / "openclaw-agent-wallet-python")

    config_data = json.loads(config_path.read_text(encoding="utf-8"))
    plugin_config = config_data["plugins"]["entries"]["agent-wallet"]["config"]
    assert config_data["plugins"]["load"]["paths"] == [str(runtime_root / ".openclaw" / "extensions" / "agent-wallet")]
    assert "agent-wallet" in config_data["plugins"]["allow"]
    assert plugin_config["packageRoot"] == str(runtime_root / "agent-wallet")
    assert plugin_config["pythonBin"] == str(runtime_root / "agent-wallet" / ".runtime-venv" / "bin" / "openclaw-agent-wallet-python")
    assert "get_evm_network" in config_data["tools"]["alsoAllow"]
    assert "set_evm_network" in config_data["tools"]["alsoAllow"]
    assert "get_evm_swap_quote" in config_data["tools"]["alsoAllow"]
    assert "swap_evm_tokens" in config_data["tools"]["alsoAllow"]
    assert "transfer_evm_native" in config_data["tools"]["alsoAllow"]
    assert "transfer_evm_token" in config_data["tools"]["alsoAllow"]
    assert "x402_search_services" in config_data["tools"]["alsoAllow"]
    assert "x402_pay_request" in config_data["tools"]["alsoAllow"]
    assert "get_flash_trade_markets" in config_data["tools"]["alsoAllow"]
    assert "get_flash_trade_positions" in config_data["tools"]["alsoAllow"]
    assert "flash_trade_open_position" in config_data["tools"]["alsoAllow"]
    assert "flash_trade_close_position" in config_data["tools"]["alsoAllow"]

    print("smoke_install_openclaw_local_config_runtime_defaults: ok")


if __name__ == "__main__":
    main()
