"""Universal installer detects hosts and keeps update enrollment/wallet state stable."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_fake_cli(path: Path, log_path: Path) -> None:
    path.write_text(
        "#!/bin/sh\n"
        f"printf '%s\\n' \"$*\" >> '{log_path}'\n"
        "exit 0\n",
        encoding="utf-8",
    )
    path.chmod(0o755)


def main() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    cli = repo_root / "bin" / "openclaw-agent-wallet.mjs"
    package_version = json.loads(
        (repo_root / "package.json").read_text(encoding="utf-8")
    )["version"]
    temp_root = Path(tempfile.mkdtemp(prefix="agentlayer-universal-installer-"))
    try:
        home = temp_root / "user-home"
        openclaw_home = home / ".openclaw"
        fake_bin = temp_root / "bin"
        fake_bin.mkdir(parents=True)
        codex_log = temp_root / "codex.log"
        claude_log = temp_root / "claude.log"
        _write_fake_cli(fake_bin / "codex", codex_log)
        for tool in ("node", "npm"):
            source = shutil.which(tool)
            assert source, f"{tool} is required"
            (fake_bin / tool).symlink_to(source)
        node_bin = str(fake_bin / "node")

        env = dict(os.environ)
        env.update(
            {
                "HOME": str(home),
                "OPENCLAW_HOME": str(openclaw_home),
                "OPENCLAW_AGENT_WALLET_PYTHON": sys.executable,
                "OPENCLAW_AGENT_WALLET_UPDATE_CLI_PATH": str(cli),
                "AGENT_WALLET_BOOT_KEY": "universal-installer-test-boot-key",
                "AGENT_WALLET_MASTER_KEY": "universal-installer-test-master-key",
                "AGENT_WALLET_APPROVAL_SECRET": "universal-installer-test-approval-secret",
                "AGENT_WALLET_VERIFY_DISABLE": "1",
                "CODEX_HOME": str(home / ".codex"),
                "AGENT_WALLET_CODEX_PLUGIN_ROOT": str(home / "plugins"),
                "AGENT_WALLET_CODEX_MARKETPLACE_PATH": str(
                    home / ".agents" / "plugins" / "marketplace.json"
                ),
                "AGENT_WALLET_CLAUDE_CODE_MARKETPLACE_DIR": str(
                    home / ".claude" / "agentlayer-local"
                ),
                "AGENT_WALLET_CLAUDE_CODE_CACHE_ROOT": str(
                    home / ".claude" / "plugins" / "cache"
                ),
                "HERMES_HOME": str(home / ".hermes"),
                "PATH": f"{fake_bin}{os.pathsep}/usr/bin{os.pathsep}/bin",
            }
        )

        before = subprocess.run(
            [node_bin, str(cli), "detect", "--json"],
            check=True,
            capture_output=True,
            text=True,
            env=env,
        )
        before_payload = json.loads(before.stdout)
        assert before_payload["detected_hosts"] == ["codex"], before_payload
        assert before_payload["runtime_installed"] is False, before_payload

        installed = subprocess.run(
            [
                node_bin,
                str(cli),
                "install",
                "--yes",
                "--skip-python-setup",
                "--skip-node-setup",
            ],
            check=True,
            capture_output=True,
            text=True,
            env=env,
        )
        install_payload = json.loads(installed.stdout)
        assert install_payload["configure_openclaw"] is False, install_payload
        assert not (openclaw_home / "openclaw.json").exists()
        assert codex_log.read_text(encoding="utf-8").strip() == "plugin add agent-wallet@local"

        runtime_base = openclaw_home / "agent-wallet-runtime"
        registry_path = runtime_base / "integrations.json"
        registry = json.loads(registry_path.read_text(encoding="utf-8"))
        assert set(registry["integrations"]) == {"codex"}, registry
        assert (runtime_base / "current").resolve().name == package_version

        provisioned_wallet_files = list((openclaw_home / "users").glob("*/wallets/*"))
        assert provisioned_wallet_files, "fresh universal install did not provision a wallet"
        protected_files = [
            openclaw_home / "sealed_keys.json",
            *provisioned_wallet_files,
            openclaw_home / "users" / "alice" / "wallets" / "solana-mainnet.json",
            openclaw_home / "wallets" / "legacy-wallet.json",
            openclaw_home / "wdk-btc-wallet" / "wallet.json",
            openclaw_home / "wdk-evm-wallet" / "wallet.json",
        ]
        for index, protected in enumerate(protected_files):
            if protected.exists():
                continue
            protected.parent.mkdir(parents=True, exist_ok=True)
            protected.write_bytes(f"wallet-state-sentinel-{index}\n".encode())
        hashes_before = {path: _sha256(path) for path in protected_files}

        # A framework appearing after onboarding must not be silently enrolled by update.
        _write_fake_cli(fake_bin / "claude", claude_log)
        updated = subprocess.run(
            [
                node_bin,
                str(cli),
                "update",
                "--yes",
                "--skip-python-setup",
                "--skip-node-setup",
            ],
            capture_output=True,
            text=True,
            env=env,
        )
        assert updated.returncode == 0, (updated.stdout, updated.stderr)
        update_payload = json.loads(updated.stdout)
        assert update_payload["ok"] is True, update_payload
        assert update_payload["command"] == "update", update_payload

        registry_after = json.loads(registry_path.read_text(encoding="utf-8"))
        assert set(registry_after["integrations"]) == {"codex"}, registry_after
        assert not claude_log.exists(), "update attempted to enroll newly detected Claude Code"
        assert not (home / ".claude" / "agentlayer-local").exists()
        assert {path: _sha256(path) for path in protected_files} == hashes_before

        print("smoke_universal_installer: ok")
    finally:
        shutil.rmtree(temp_root, ignore_errors=True)


if __name__ == "__main__":
    main()
