"""Smoke test for the GitHub bootstrap installer wrapper."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tarfile
from pathlib import Path


def _copy_file(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)


def main() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    temp_root = Path("/tmp/openclaw-install-from-github-smoke")
    if temp_root.exists():
        shutil.rmtree(temp_root)
    temp_root.mkdir(parents=True, exist_ok=True)

    bundle_root = temp_root / "bundle-root"
    bundle_prefix = "openclaw-agent-wallet-bundle-smoke"
    bundle_tree = bundle_root / bundle_prefix
    bundle_tree.mkdir(parents=True, exist_ok=True)

    _copy_file(repo_root / "setup.sh", bundle_tree / "setup.sh")
    _copy_file(repo_root / "agent-wallet" / ".env.example", bundle_tree / "agent-wallet" / ".env.example")
    _copy_file(
        repo_root / "agent-wallet" / "scripts" / "install_agent_wallet.py",
        bundle_tree / "agent-wallet" / "scripts" / "install_agent_wallet.py",
    )

    (bundle_tree / ".openclaw" / "extensions" / "agent-wallet").mkdir(parents=True, exist_ok=True)
    (bundle_tree / "wdk-btc-wallet").mkdir(parents=True, exist_ok=True)
    (bundle_tree / "wdk-evm-wallet").mkdir(parents=True, exist_ok=True)
    (bundle_tree / "wdk-btc-wallet" / "package.json").write_text('{"name":"wdk-btc-wallet"}\n', encoding="utf-8")
    (bundle_tree / "wdk-evm-wallet" / "package.json").write_text('{"name":"wdk-evm-wallet"}\n', encoding="utf-8")

    asset_path = temp_root / f"{bundle_prefix}.tar.gz"
    with tarfile.open(asset_path, "w:gz") as archive:
        archive.add(bundle_tree, arcname=bundle_prefix)

    release_metadata = {
        "tag_name": "v-smoke",
        "assets": [
            {
                "name": f"{bundle_prefix}.tar.gz",
                "browser_download_url": asset_path.resolve().as_uri(),
            }
        ],
    }
    release_json_path = temp_root / "release.json"
    release_json_path.write_text(json.dumps(release_metadata), encoding="utf-8")

    install_root = temp_root / "install-root"
    openclaw_home = temp_root / "openclaw-home"
    bootstrap_script = repo_root / "install-from-github.sh"

    env = dict(os.environ)
    env["OPENCLAW_HOME"] = str(openclaw_home)
    env["OPENCLAW_INSTALL_RELEASE_METADATA_URL"] = release_json_path.resolve().as_uri()
    env["OPENCLAW_INSTALL_ASSET_PREFIX"] = "openclaw-agent-wallet-bundle-"
    env["OPENCLAW_INSTALL_ROOT"] = str(install_root)
    env["AGENT_WALLET_BOOT_KEY"] = "test-boot-key-for-github-bootstrap"
    env["AGENT_WALLET_MASTER_KEY"] = "test-master-key-for-github-bootstrap"
    env["AGENT_WALLET_APPROVAL_SECRET"] = "test-approval-secret-for-github-bootstrap"

    result = subprocess.run(
        [
            "sh",
            str(bootstrap_script),
            "--config-path",
            str(temp_root / "openclaw.json"),
            "--env-path",
            str(temp_root / ".env"),
            "--skip-python-setup",
            "--skip-node-setup",
            "--dry-run",
        ],
        capture_output=True,
        text=True,
        check=True,
        env=env,
    )
    payload = json.loads(result.stdout)
    current_root = (install_root / "current").resolve()
    assert payload["ok"] is True
    assert current_root.exists()
    assert (current_root / "setup.sh").exists()
    assert (current_root / "agent-wallet" / "scripts" / "install_agent_wallet.py").exists()
    assert (current_root / ".openclaw" / "extensions" / "agent-wallet").exists()
    assert (current_root / "wdk-btc-wallet" / "package.json").exists()
    assert (current_root / "wdk-evm-wallet" / "package.json").exists()
    assert Path(payload["package_root"]).resolve() == current_root / "agent-wallet"
    assert Path(payload["wdk_btc_root"]).resolve() == current_root / "wdk-btc-wallet"
    assert Path(payload["wdk_evm_root"]).resolve() == current_root / "wdk-evm-wallet"

    print("smoke_install_from_github: ok")


if __name__ == "__main__":
    main()
