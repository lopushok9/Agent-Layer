"""Smoke test for update dry-run boot-key auto-discovery."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path


def main() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    cli = repo_root / "bin" / "openclaw-agent-wallet.mjs"
    package_version = json.loads((repo_root / "package.json").read_text(encoding="utf-8"))["version"]

    temp_root = Path("/tmp/openclaw-update-boot-key-discovery-smoke")
    if temp_root.exists():
        shutil.rmtree(temp_root)
    temp_root.mkdir(parents=True, exist_ok=True)

    runtime_base = temp_root / "agent-wallet-runtime"
    runtime_root = runtime_base / "releases" / package_version
    current_link = runtime_base / "current"
    runtime_root.mkdir(parents=True, exist_ok=True)
    current_link.parent.mkdir(parents=True, exist_ok=True)
    current_link.symlink_to(runtime_root, target_is_directory=True)

    sealed_keys = temp_root / "sealed_keys.json"
    sealed_keys.write_text('{"encrypted":true}\n', encoding="utf-8")
    boot_key_file = runtime_base / "boot-key"
    boot_key_file.write_text("boot-key-from-default-file\n", encoding="utf-8")

    env = {
        key: value
        for key, value in os.environ.items()
        if key not in {"AGENT_WALLET_BOOT_KEY", "AGENT_WALLET_BOOT_KEY_FILE"}
    }
    env["OPENCLAW_HOME"] = str(temp_root)
    env["OPENCLAW_AGENT_WALLET_UPDATE_CLI_PATH"] = str(cli)

    result = subprocess.run(
        [
            "node",
            str(cli),
            "update",
            "--yes",
            "--dry-run",
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
    assert payload["dry_run"] is True
    assert payload["current_version"] == package_version
    assert payload["target_version"] == package_version
    assert not (runtime_base / "update-journal.json").exists()

    print("smoke_update_boot_key_discovery: ok")


if __name__ == "__main__":
    main()
