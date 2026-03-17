"""Smoke test for the sealed-keys installer script."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agent_wallet.sealed_keys import resolve_sealed_keys_path, unseal_keys  # noqa: E402


def _run_script(env: dict[str, str], *args: str) -> dict[str, object]:
    script = Path(__file__).resolve().parents[1] / "scripts" / "install_openclaw_sealed_keys.py"
    result = subprocess.run(
        [sys.executable, str(script), *args],
        capture_output=True,
        text=True,
        check=True,
        env=env,
    )
    return json.loads(result.stdout)


def main() -> None:
    temp_home = Path("/tmp/openclaw-install-sealed-keys-smoke")
    if temp_home.exists():
        shutil.rmtree(temp_home)

    env = dict(os.environ)
    env["OPENCLAW_HOME"] = str(temp_home)
    env["AGENT_WALLET_BOOT_KEY"] = "test-boot-key-for-installer-smoke"
    env["AGENT_WALLET_MASTER_KEY"] = "master-from-installer"
    env["AGENT_WALLET_APPROVAL_SECRET"] = "approval-from-installer"
    env.pop("SOLANA_AGENT_PRIVATE_KEY", None)
    os.environ["OPENCLAW_HOME"] = env["OPENCLAW_HOME"]

    first = _run_script(env)
    assert first["ok"] is True
    assert first["updated_keys"] == ["approval_secret", "master_key"]
    sealed = unseal_keys(env["AGENT_WALLET_BOOT_KEY"])
    assert sealed["master_key"] == "master-from-installer"
    assert sealed["approval_secret"] == "approval-from-installer"

    env.pop("AGENT_WALLET_MASTER_KEY", None)
    env["SOLANA_AGENT_PRIVATE_KEY"] = "private-from-installer"
    second = _run_script(env)
    assert second["replaced"] is False
    sealed = unseal_keys(env["AGENT_WALLET_BOOT_KEY"])
    assert sealed["master_key"] == "master-from-installer"
    assert sealed["approval_secret"] == "approval-from-installer"
    assert sealed["private_key"] == "private-from-installer"

    env["AGENT_WALLET_MASTER_KEY"] = "replacement-master"
    env.pop("AGENT_WALLET_APPROVAL_SECRET", None)
    env.pop("SOLANA_AGENT_PRIVATE_KEY", None)
    third = _run_script(env, "--replace")
    assert third["replaced"] is True
    sealed = unseal_keys(env["AGENT_WALLET_BOOT_KEY"])
    assert sealed == {"master_key": "replacement-master"}
    assert resolve_sealed_keys_path().exists()

    print("smoke_install_openclaw_sealed_keys: ok")


if __name__ == "__main__":
    main()
