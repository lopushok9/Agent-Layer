"""Smoke test for automatic sealed-key setup in install_openclaw_local_config.py."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agent_wallet.sealed_keys import unseal_keys  # noqa: E402


def main() -> None:
    temp_root = Path("/tmp/openclaw-install-config-sealed-smoke")
    if temp_root.exists():
        shutil.rmtree(temp_root)
    temp_root.mkdir(parents=True, exist_ok=True)

    config_path = temp_root / "openclaw.json"
    config_path.write_text(
        json.dumps({"plugins": {"entries": {}}, "tools": {"alsoAllow": []}}, indent=2) + "\n",
        encoding="utf-8",
    )

    env = dict(os.environ)
    env["OPENCLAW_HOME"] = str(temp_root)
    env["AGENT_WALLET_BOOT_KEY"] = "test-boot-key-for-install-config-smoke"
    env["AGENT_WALLET_MASTER_KEY"] = "installer-master-key"
    env["AGENT_WALLET_APPROVAL_SECRET"] = "installer-approval-secret"
    env["SOLANA_AGENT_PRIVATE_KEY"] = "installer-private-key"
    os.environ["OPENCLAW_HOME"] = env["OPENCLAW_HOME"]

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
    assert payload["sealed_keys_path"]

    config_data = json.loads(config_path.read_text(encoding="utf-8"))
    plugin = config_data["plugins"]["entries"]["agent-wallet"]
    assert plugin["enabled"] is True
    assert plugin["config"]["backend"] == "solana_local"
    assert "masterKey" not in plugin["config"]
    assert "approvalSecret" not in plugin["config"]
    assert "privateKey" not in plugin["config"]

    sealed = unseal_keys(env["AGENT_WALLET_BOOT_KEY"])
    assert sealed["master_key"] == "installer-master-key"
    assert sealed["approval_secret"] == "installer-approval-secret"
    assert sealed["private_key"] == "installer-private-key"

    print("smoke_install_openclaw_local_config_sealed: ok")


if __name__ == "__main__":
    main()
