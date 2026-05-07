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

    runtime_root = temp_root / "agent-wallet-runtime" / "current"
    runtime_extension = runtime_root / ".openclaw" / "extensions" / "agent-wallet"
    runtime_package = runtime_root / "agent-wallet"
    runtime_venv_bin = runtime_package / ".runtime-venv" / "bin"
    runtime_extension.mkdir(parents=True, exist_ok=True)
    runtime_package.mkdir(parents=True, exist_ok=True)
    runtime_venv_bin.mkdir(parents=True, exist_ok=True)

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
        [sys.executable, str(script), "--config-path", str(config_path)],
        capture_output=True,
        text=True,
        check=True,
        env=env,
    )

    payload = json.loads(completed.stdout)
    assert payload["ok"] is True
    assert Path(payload["extension_path"]).resolve() == runtime_extension.resolve()
    assert Path(payload["package_root"]).resolve() == runtime_package.resolve()
    assert Path(payload["python_bin"]).resolve() == wrapper.resolve()

    config_data = json.loads(config_path.read_text(encoding="utf-8"))
    plugin_config = config_data["plugins"]["entries"]["agent-wallet"]["config"]
    assert config_data["plugins"]["load"]["paths"] == [str(runtime_extension.resolve())]
    assert plugin_config["packageRoot"] == str(runtime_package.resolve())
    assert plugin_config["pythonBin"] == str(wrapper.resolve())

    print("smoke_install_openclaw_local_config_runtime_defaults: ok")


if __name__ == "__main__":
    main()
