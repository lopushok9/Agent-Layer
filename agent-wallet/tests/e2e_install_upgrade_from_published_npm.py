"""Upgrade the published compatibility floor to the exact local npm artifact.

The entire flow runs under temporary HOME/OPENCLAW_HOME directories and forces
the plaintext keystore backend inside that sandbox. It never accesses the
developer's OS keystore or AgentLayer runtime.
"""

from __future__ import annotations

import atexit
import hashlib
import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
OLD_VERSION = "0.1.53"
USER_ID = "published-floor-upgrade"


def run(
    args: list[str],
    *,
    cwd: Path,
    env: dict[str, str],
    timeout: int = 1500,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        args,
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    if check and result.returncode != 0:
        raise AssertionError(
            f"command failed ({result.returncode}): {' '.join(args)}\n"
            f"stdout:\n{result.stdout[-4000:]}\n"
            f"stderr:\n{result.stderr[-4000:]}"
        )
    return result


def npm_pack(spec: str, *, destination: Path, env: dict[str, str]) -> Path:
    result = run(
        ["npm", "pack", spec, "--json", "--pack-destination", str(destination)],
        cwd=REPO_ROOT,
        env=env,
    )
    payload = json.loads(result.stdout)
    archive = destination / payload[0]["filename"]
    assert archive.is_file(), archive
    return archive


def install_cli(archive: Path, *, destination: Path, env: dict[str, str]) -> Path:
    destination.mkdir(parents=True, exist_ok=True)
    run(
        [
            "npm",
            "install",
            "--ignore-scripts",
            "--no-audit",
            "--no-fund",
            "--prefix",
            str(destination),
            str(archive),
        ],
        cwd=destination,
        env=env,
    )
    cli = (
        destination
        / "node_modules"
        / "@agentlayer.tech"
        / "wallet"
        / "bin"
        / "openclaw-agent-wallet.mjs"
    )
    assert cli.is_file(), cli
    return cli


def runtime_python(runtime_root: Path) -> Path:
    for relative in (
        Path("agent-wallet/.venv/bin/python"),
        Path("agent-wallet/.runtime-venv/bin/python"),
    ):
        candidate = runtime_root / relative
        if candidate.is_file():
            return candidate
    raise AssertionError(f"Python runtime missing under {runtime_root}")


def python_json(
    python: Path,
    code: str,
    *,
    runtime_root: Path,
    env: dict[str, str],
) -> dict[str, object]:
    result = run(
        [str(python), "-c", code],
        cwd=runtime_root / "agent-wallet",
        env=env,
        timeout=180,
    )
    return json.loads(result.stdout)


def read_env_value(path: Path, name: str) -> str:
    for line in path.read_text(encoding="utf-8").splitlines():
        prefix = f"{name}="
        if line.startswith(prefix):
            return line[len(prefix) :].strip()
    return ""


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    new_version = (REPO_ROOT / "VERSION").read_text(encoding="utf-8").strip()
    assert new_version != OLD_VERSION

    temp_root = Path(tempfile.mkdtemp(prefix="agentlayer-published-upgrade-"))
    atexit.register(shutil.rmtree, temp_root, ignore_errors=True)
    home = temp_root / "home"
    openclaw_home = home / ".openclaw"
    artifacts = temp_root / "artifacts"
    artifacts.mkdir(parents=True)

    env = dict(os.environ)
    env.update(
        {
            "HOME": str(home),
            "OPENCLAW_HOME": str(openclaw_home),
            "HERMES_HOME": str(home / ".hermes"),
            "CODEX_HOME": str(home / ".codex"),
            "AGENT_WALLET_CODEX_PLUGIN_ROOT": str(home / ".codex/plugins"),
            "AGENT_WALLET_CODEX_MARKETPLACE_PATH": str(home / ".codex/marketplace.json"),
            "AGENT_WALLET_CLAUDE_CODE_MARKETPLACE_DIR": str(home / ".claude/plugins"),
            "AGENT_WALLET_CLAUDE_CODE_CACHE_ROOT": str(home / ".claude/cache"),
            "AGENT_WALLET_KEYSTORE_BACKEND": "plaintext",
            "AGENT_WALLET_KEYSTORE_SERVICE": "ai.agentlayer.wallet.published-upgrade-test",
            "AGENT_WALLET_NO_TELEMETRY": "1",
            "AGENT_WALLET_DISABLE_UPDATE_CHECK": "1",
            "npm_config_cache": str(temp_root / "npm-cache"),
            "PIP_DEFAULT_TIMEOUT": "120",
            "PIP_RETRIES": "8",
            "PIP_DISABLE_PIP_VERSION_CHECK": "1",
            "PIP_CACHE_DIR": str(Path(tempfile.gettempdir()) / "agentlayer-upgrade-pip-cache"),
        }
    )
    for name in (
        "AGENT_WALLET_BOOT_KEY",
        "AGENT_WALLET_BOOT_KEY_FILE",
        "AGENT_WALLET_MASTER_KEY",
        "AGENT_WALLET_APPROVAL_SECRET",
        "AGENT_WALLET_VERIFY_DISABLE",
        "OPENCLAW_INSTALL_ROOT",
        "OPENCLAW_INSTALL_FINAL_ROOT",
    ):
        env.pop(name, None)

    old_archive = npm_pack(
        f"@agentlayer.tech/wallet@{OLD_VERSION}",
        destination=artifacts,
        env=env,
    )
    new_archive = npm_pack(".", destination=artifacts, env=env)
    old_cli = install_cli(old_archive, destination=temp_root / "old-cli", env=env)
    new_cli = install_cli(new_archive, destination=temp_root / "new-cli", env=env)

    runtime_base = openclaw_home / "agent-wallet-runtime"
    old_root = runtime_base / "releases" / OLD_VERSION
    new_root = runtime_base / "releases" / new_version
    old_install_env = {
        **env,
        "AGENT_WALLET_BOOT_KEY": "published-floor-test-boot-key",
        "AGENT_WALLET_MASTER_KEY": "published-floor-test-master-key",
        "AGENT_WALLET_APPROVAL_SECRET": "published-floor-test-approval-secret",
    }

    run(
        [
            "node",
            str(old_cli),
            "install",
            "--yes",
            "--backend",
            "solana_local",
            "--user-id",
            USER_ID,
            "--skip-node-setup",
            "--config-path",
            str(openclaw_home / "openclaw.json"),
            "--env-path",
            str(openclaw_home / "agent-wallet.env"),
        ],
        cwd=temp_root,
        env=old_install_env,
    )
    assert (runtime_base / "current").resolve() == old_root.resolve()

    old_env_path = old_root / "agent-wallet" / ".env"
    old_boot_key = read_env_value(old_env_path, "AGENT_WALLET_BOOT_KEY")
    assert old_boot_key, "published 0.1.53 install did not persist its boot key"
    old_boot_fingerprint = hashlib.sha256(old_boot_key.encode("utf-8")).hexdigest()

    old_python = runtime_python(old_root)
    sealed_path = openclaw_home / "sealed_keys.json"
    assert sealed_path.is_file(), "published 0.1.53 did not create sealed secrets"
    old_wallet_env = {**env, "AGENT_WALLET_BOOT_KEY": old_boot_key}
    created = python_json(
        old_python,
        (
            "import json\n"
            "from agent_wallet.user_wallets import ensure_user_solana_wallet\n"
            f"print(json.dumps(ensure_user_solana_wallet({USER_ID!r}, network='mainnet')))\n"
        ),
        runtime_root=old_root,
        env=old_wallet_env,
    )
    wallet_path = Path(str(created["path"]))
    old_address = str(created["address"])
    assert wallet_path.is_file()
    wallet_hash_before = sha256_file(wallet_path)
    sealed_hash_before = sha256_file(sealed_path)

    run(
        [
            "node",
            str(new_cli),
            "install",
            "--yes",
            "--runtime-only",
            "--backend",
            "none",
            "--skip-node-setup",
        ],
        cwd=temp_root,
        env=env,
    )
    assert (runtime_base / "current").resolve() == new_root.resolve()
    assert (runtime_base / "previous").resolve() == old_root.resolve()

    new_python = runtime_python(new_root)
    verified = python_json(
        new_python,
        (
            "import hashlib, json\n"
            "from agent_wallet.config import resolve_boot_key\n"
            "from agent_wallet.keystore import resolve_keystore\n"
            "from agent_wallet.user_wallets import get_user_wallet_storage_info\n"
            "key = resolve_boot_key()\n"
            "print(json.dumps({\n"
            "  'backend': resolve_keystore().backend_id,\n"
            "  'boot_fingerprint': hashlib.sha256(key.encode()).hexdigest(),\n"
            f"  'wallet': get_user_wallet_storage_info({USER_ID!r}, network='mainnet'),\n"
            "}))\n"
        ),
        runtime_root=new_root,
        env=env,
    )
    assert verified["backend"] == "plaintext-file", verified
    assert verified["boot_fingerprint"] == old_boot_fingerprint, (
        "upgrade changed the boot key"
    )
    wallet = dict(verified["wallet"])
    assert wallet["address"] == old_address, "upgrade changed the Solana address"
    assert wallet["pinned_address"] == old_address, "wallet pin changed during upgrade"
    assert sha256_file(wallet_path) == wallet_hash_before, "wallet file bytes changed"
    assert sha256_file(sealed_path) == sealed_hash_before, "sealed secret bundle changed"

    new_env_path = new_root / "agent-wallet" / ".env"
    if new_env_path.exists():
        assert "AGENT_WALLET_BOOT_KEY=" not in new_env_path.read_text(encoding="utf-8")

    print(
        "e2e_install_upgrade_from_published_npm OK: "
        f"{OLD_VERSION} -> {new_version}, wallet and boot-key identity preserved"
    )


if __name__ == "__main__":
    main()
