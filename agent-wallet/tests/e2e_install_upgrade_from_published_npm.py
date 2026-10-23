"""Upgrade the published compatibility floor to the exact local npm artifact.

The entire flow runs under temporary HOME/OPENCLAW_HOME directories and forces
the plaintext keystore backend inside that sandbox. It never accesses the
developer's OS keystore or AgentLayer runtime.
"""

from __future__ import annotations

import atexit
import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
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
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--old-version', default=OLD_VERSION)
    parser.add_argument('--candidate', type=Path, help='Exact previously packed release artifact')
    parser.add_argument('--evm-dependencies', type=Path,
                        help='Optional read-only SDK dependency cache for encrypted EVM identity verification')
    args = parser.parse_args()
    old_version = args.old_version
    new_version = (REPO_ROOT / "VERSION").read_text(encoding="utf-8").strip()
    assert new_version != old_version

    # Keep per-home Unix socket paths below the macOS sun_path limit as well.
    temp_root = Path(tempfile.mkdtemp(prefix="al-upgrade-", dir="/tmp"))
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
            "USER": USER_ID,
            "AGENT_WALLET_USER_ID": USER_ID,
            "OPENCLAW_AGENT_WALLET_USER_ID": USER_ID,
            "OPENCLAW_AGENT_WALLET_PYTHON": sys.executable,
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
        f"@agentlayer.tech/wallet@{old_version}",
        destination=artifacts,
        env=env,
    )
    new_archive = args.candidate.resolve() if args.candidate else npm_pack(".", destination=artifacts, env=env)
    old_cli = install_cli(old_archive, destination=temp_root / "old-cli", env=env)
    new_cli = install_cli(new_archive, destination=temp_root / "new-cli", env=env)

    runtime_base = openclaw_home / "agent-wallet-runtime"
    old_root = runtime_base / "releases" / old_version
    new_root = runtime_base / "releases" / new_version
    old_install_env = {
        **env,
        "AGENT_WALLET_BOOT_KEY": "published-floor-test-boot-key",
        "AGENT_WALLET_MASTER_KEY": "published-floor-test-master-key",
        "AGENT_WALLET_APPROVAL_SECRET": "published-floor-test-approval-secret",
    }
    # 0.1.53 predates the required FastMCP dependency in pyproject.toml. This
    # bootstrap reconstructs an existing old installation, not a new-user
    # acceptance test of that historical release. Only its MCP handshake is
    # skipped; the candidate installation below runs all verification normally.
    if old_version == '0.1.53':
        old_install_env['AGENT_WALLET_VERIFY_DISABLE'] = '1'

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
    old_python = runtime_python(old_root)
    old_boot_key = read_env_value(old_env_path, "AGENT_WALLET_BOOT_KEY") if old_env_path.exists() else ''
    if not old_boot_key:
        old_boot_key = str(python_json(old_python,
            "import json; from agent_wallet.config import resolve_boot_key; print(json.dumps({'key': resolve_boot_key()}))",
            runtime_root=old_root, env=env)['key'])
    assert old_boot_key, f"published {old_version} install did not persist its boot key"
    old_boot_fingerprint = hashlib.sha256(old_boot_key.encode("utf-8")).hexdigest()

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
    evm_identity = None
    evm_probe = '''
import { LocalEvmVault } from './src/local_vault.js';
import { HDNodeWallet } from 'ethers';
const [dataDir, existingId] = process.argv.slice(2);
const vault = new LocalEvmVault({dataDir, network: 'base'});
const walletId = existingId || (await vault.createWallet({password: 'isolated-evm-password', network: 'base'})).walletId;
const value = await vault.revealSeedPhrase({walletId, password: 'isolated-evm-password'});
const address = HDNodeWallet.fromPhrase(value.seedPhrase).address;
console.log(JSON.stringify({walletId, address}));
'''
    def probe_evm(root, wallet_id=''):
        project = root / 'wdk-evm-wallet'
        dependencies = project / 'node_modules'
        if not dependencies.exists():
            dependencies.symlink_to(args.evm_dependencies.resolve(), target_is_directory=True)
        script = project / 'upgrade-identity-probe.mjs'
        script.write_text(evm_probe)
        try:
            return json.loads(run(['node', str(script), str(openclaw_home / 'wdk-evm-wallet'), wallet_id],
                                  cwd=project, env=env, timeout=180).stdout)
        finally:
            script.unlink(missing_ok=True)
    if args.evm_dependencies:
        evm_identity = probe_evm(old_root)
    # These old public releases predate card custody. Seed an already-existing
    # encrypted vault using the candidate's format, then exercise the real
    # installer over it. No real card, OS Keychain or developer state is used.
    candidate_package = new_cli.parents[1] / 'agent-wallet'
    fixture_env = {**old_wallet_env, 'PYTHONPATH': str(candidate_package)}
    seed = python_json(old_python, '''
import json
from agent_wallet.card_vault import CardVault
from agent_wallet.card_runtime_secrets import RuntimeVaultStorage
from agent_wallet.sealed_keys import seal_keys, unseal_keys
from agent_wallet.config import resolve_boot_key
vault = CardVault('published-floor-upgrade')
vault.initialize('isolated-fixture-password')
ref = vault.deposit({'fixture': 'encrypted-owner-card', 'number': '4242424242424242'})
RuntimeVaultStorage(vault, 'use').save(ref, {'fields': {'card.number': '4242424242424242'}})
RuntimeVaultStorage(vault, 'operation').save('a' * 32, {'status': 'outcome_unknown', 'attempts': 1})
RuntimeVaultStorage(vault, 'browser').save('b' * 32, {'session_id': 'old-direct-browser', 'state': 'closed'})
boot = resolve_boot_key()
secrets = unseal_keys(boot)
secrets['kernel_api_key'] = 'isolated-existing-personal-key'
seal_keys(boot, secrets)
print(json.dumps({'ref': ref, 'root': str(vault.root)}))
''', runtime_root=candidate_package.parent, env=fixture_env)
    vault_root = Path(str(seed['root']))
    preserved_files = {p: sha256_file(p) for p in vault_root.iterdir() if p.is_file()}
    # Include encrypted EVM seed/config files created by the original installer.
    for directory in ('wallets', 'wdk-evm-wallet', 'evm-wallets'):
        for file in (openclaw_home / directory).rglob('*'):
            if file.is_file() and file.suffix != '.sock':
                preserved_files[file] = sha256_file(file)
    config_path = openclaw_home / 'openclaw.json'
    config = json.loads(config_path.read_text())
    config['upgrade_test_custom_setting'] = {'theme': 'preserve', 'limits': [5, 10]}
    config_path.write_text(json.dumps(config))
    settings_path = home / '.codex' / 'config.toml'
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    settings_path.write_text('model = "user-chosen-model"\n[custom]\nkeep = true\n')
    preserved_files[settings_path] = sha256_file(settings_path)
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
    for file, digest in preserved_files.items():
        assert sha256_file(file) == digest, f'upgrade modified existing state: {file.relative_to(home)}'
    assert json.loads(config_path.read_text())['upgrade_test_custom_setting'] == config['upgrade_test_custom_setting']
    restored = python_json(new_python, f'''
import json
from agent_wallet.card_vault import CardVault
from agent_wallet.card_runtime_secrets import RuntimeVaultStorage
from agent_wallet.config import resolve_kernel_api_key
vault = CardVault({USER_ID!r})
assert vault.read({seed['ref']!r}, vault.unlock('isolated-fixture-password'))['fixture'] == 'encrypted-owner-card'
assert RuntimeVaultStorage(vault, 'use').load({seed['ref']!r})['fields']['card.number'] == '4242424242424242'
assert RuntimeVaultStorage(vault, 'operation').load('a' * 32)['status'] == 'outcome_unknown'
assert RuntimeVaultStorage(vault, 'browser').load('b' * 32)['session_id'] == 'old-direct-browser'
assert resolve_kernel_api_key() == 'isolated-existing-personal-key'
print(json.dumps({{'vault_decrypted': True}}))
''', runtime_root=new_root, env=env)
    assert restored['vault_decrypted'] is True
    if evm_identity:
        assert probe_evm(new_root, evm_identity['walletId']) == evm_identity, 'EVM seed/address changed'

    new_env_path = new_root / "agent-wallet" / ".env"
    if new_env_path.exists():
        assert "AGENT_WALLET_BOOT_KEY=" not in new_env_path.read_text(encoding="utf-8")

    print(
        "e2e_install_upgrade_from_published_npm OK: "
        f"{old_version} -> {new_version}, wallets, boot key, encrypted vault, operations, personal Kernel key and settings preserved; "
        f"candidate sha256={sha256_file(new_archive)}"
    )
    if evm_identity:
        print('Encrypted EVM vault decrypted with the candidate; seed-derived address and wallet ID unchanged')


if __name__ == "__main__":
    main()
