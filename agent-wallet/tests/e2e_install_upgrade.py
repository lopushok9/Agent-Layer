"""Upgrade acceptance: the real installer over a legacy plaintext-.env layout.

Seeds what a pre-keystore release (<= 0.1.62) left on disk — sealed_keys.json
encrypted with boot key K0, plus an old release whose agent-wallet/.env holds
AGENT_WALLET_BOOT_KEY=K0 (with `current` pointing at it) — then runs the real
Node installer with NO key in the environment and asserts the upgrade contract:

  1. the installer adopts K0 from the current runtime's .env — it must never
     generate a fresh key over existing sealed secrets;
  2. K0 is provisioned into the OS keystore and the NEW release .env is clean;
  3. the sealed secrets still unseal through the new runtime with no env key;
  4. the old release's plaintext .env is swept on native keystores (in practice
     already during install: the verify handshake boots the runtime, whose
     startup migration stores K0 and sweeps); on the plaintext fallback
     (Linux CI) the sweep deliberately never happens — both are asserted.

Historically the upgrade path is where installs broke (0.1.61-0.1.64 were all
upgrade bugs), so this is the highest-value E2E. Slow (real venv + pip); runs
from install-e2e.yml. The driver imports agent_wallet only to SEED the legacy
sealed file (CI pip-installs the package); post-install assertions all go
through the installed release's venv python.
"""

from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
CLI = REPO_ROOT / "bin" / "openclaw-agent-wallet.mjs"
TEST_SERVICE = "ai.agentlayer.wallet.e2etest.upgrade"
LEGACY_KEY = "legacy-boot-key-" + "d00d" * 12
OLD_VERSION = "0.0.1"

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def last_json_object(text: str) -> dict:
    lines = text.splitlines()
    for idx in range(len(lines) - 1, -1, -1):
        if lines[idx].strip() == "{":
            try:
                return json.loads("\n".join(lines[idx:]))
            except json.JSONDecodeError:
                continue
    raise AssertionError(f"no JSON payload found in installer output:\n{text[-2000:]}")


def expected_backend() -> str:
    configured = os.environ.get("AGENT_WALLET_E2E_EXPECT_BACKEND", "").strip()
    if configured:
        return configured
    return "macos-keychain" if platform.system() == "Darwin" else "plaintext-file"


def resolve_venv_python(runtime_root: Path) -> Path:
    for rel in (".venv", ".runtime-venv"):
        candidate = runtime_root / "agent-wallet" / rel / "bin" / "python"
        if candidate.exists():
            return candidate
    raise AssertionError(f"no venv python under {runtime_root}/agent-wallet")


def main() -> None:
    temp_home = Path(tempfile.mkdtemp(prefix="openclaw-e2e-upgrade-"))
    env = dict(os.environ)
    env["OPENCLAW_HOME"] = str(temp_home)
    env["AGENT_WALLET_KEYSTORE_SERVICE"] = TEST_SERVICE
    for var in (
        "AGENT_WALLET_BOOT_KEY",
        "AGENT_WALLET_BOOT_KEY_FILE",
        "AGENT_WALLET_MASTER_KEY",
        "AGENT_WALLET_APPROVAL_SECRET",
        "AGENT_WALLET_KEYSTORE_BACKEND",
        "AGENT_WALLET_VERIFY_DISABLE",
    ):
        env.pop(var, None)

    expect = expected_backend()
    version = (REPO_ROOT / "VERSION").read_text(encoding="utf-8").strip()
    runtime_base = temp_home / "agent-wallet-runtime"
    new_root = runtime_base / "releases" / version
    old_env_path = runtime_base / "releases" / OLD_VERSION / "agent-wallet" / ".env"
    venv_python: Path | None = None

    # --- Seed the legacy layout (driver-side; the only agent_wallet import) ---
    os.environ["OPENCLAW_HOME"] = str(temp_home)
    from agent_wallet.sealed_keys import seal_keys  # noqa: E402

    sealed_path = seal_keys(LEGACY_KEY, {
        "master_key": "e2e-upgrade-master",
        "approval_secret": "e2e-upgrade-approval",
        "private_key": "e2e-upgrade-material",
    })
    assert sealed_path == temp_home / "sealed_keys.json", sealed_path

    old_env_path.parent.mkdir(parents=True, exist_ok=True)
    old_env_path.write_text(
        f"AGENT_WALLET_BOOT_KEY={LEGACY_KEY}\nAGENT_WALLET_KEEP_ME=other-config\n",
        encoding="utf-8",
    )
    (runtime_base / "current").symlink_to(runtime_base / "releases" / OLD_VERSION)

    def run_py(code: str) -> subprocess.CompletedProcess[str]:
        assert venv_python is not None
        return subprocess.run(
            [str(venv_python), "-c", code],
            capture_output=True, text=True, timeout=120,
            cwd=new_root / "agent-wallet", env=env,
        )

    try:
        # --- The upgrade: real installer, no key anywhere in the environment ---
        install = subprocess.run(
            [
                "node", str(CLI), "install", "--yes",
                "--backend", "none",
                "--config-path", str(temp_home / "openclaw.json"),
                "--env-path", str(temp_home / ".env"),
                "--skip-node-setup",
            ],
            capture_output=True, text=True, timeout=1500, env=env,
        )
        assert install.returncode == 0, (
            f"upgrade install failed rc={install.returncode}\nstdout:\n{install.stdout[-3000:]}\n"
            f"stderr:\n{install.stderr[-3000:]}"
        )
        payload = last_json_object(install.stdout)
        assert payload.get("ok") is True, payload
        assert (runtime_base / "current").resolve() == new_root.resolve()
        venv_python = resolve_venv_python(new_root)

        # Key identity: the keystore must hold exactly K0, not a fresh key.
        probe = run_py(
            "import json\n"
            "from agent_wallet.config import read_boot_key_from_keystore\n"
            "from agent_wallet.keystore import resolve_keystore\n"
            "print(json.dumps({'backend': resolve_keystore().backend_id,"
            " 'key': read_boot_key_from_keystore()}))\n"
        )
        assert probe.returncode == 0, probe.stderr
        info = json.loads(probe.stdout)
        assert info["backend"] == expect, f"expected backend {expect!r}, got {info['backend']!r}"
        assert info["key"] == LEGACY_KEY, (
            "upgrade replaced the boot key — sealed secrets would be lost! "
            f"got {info['key']!r}"
        )

        # The new release .env must be clean of plaintext.
        new_env_file = new_root / "agent-wallet" / ".env"
        if new_env_file.exists():
            assert "AGENT_WALLET_BOOT_KEY=" not in new_env_file.read_text(encoding="utf-8"), (
                "plaintext boot key leaked into the new release .env"
            )

        # Sealed secrets survive the upgrade: unseal with nothing in the env.
        unsealed = run_py(
            "import json\n"
            "from agent_wallet.config import resolve_approval_secret, resolve_wallet_master_key\n"
            "print(json.dumps({'master': resolve_wallet_master_key(),"
            " 'approval': resolve_approval_secret()}))\n"
        )
        assert unsealed.returncode == 0, unsealed.stderr
        secrets = json.loads(unsealed.stdout)
        assert secrets["master"] == "e2e-upgrade-master", secrets
        assert secrets["approval"] == "e2e-upgrade-approval", secrets

        # Plaintext sweep of the OLD release. On native keystores the sweep
        # already happens DURING install (the verify handshake boots the runtime,
        # whose startup migration stores K0 and sweeps every plaintext copy), so
        # an explicit re-run here must be an idempotent no-op — assert the final
        # state, not who swept. The plaintext fallback deliberately never sweeps.
        migration = run_py(
            "import json\n"
            "from agent_wallet.boot_key_migration import migrate_boot_key_to_keystore\n"
            "print(json.dumps(migrate_boot_key_to_keystore()))\n"
        )
        assert migration.returncode == 0, migration.stderr
        result = json.loads(migration.stdout)
        old_env_content = old_env_path.read_text(encoding="utf-8")
        if expect == "plaintext-file":
            assert result["reason"] == "no-os-keystore", result
            assert LEGACY_KEY in old_env_content, "fallback migration must not sweep"
        else:
            assert LEGACY_KEY not in old_env_content, (
                f"old release .env still holds the plaintext key:\n{old_env_content}"
            )
            assert "AGENT_WALLET_KEEP_ME=other-config" in old_env_content, (
                "sweep must only strip the boot-key line, not other config"
            )
    finally:
        if venv_python is not None:
            subprocess.run(
                [str(venv_python), "-c",
                 "from agent_wallet.keystore import resolve_keystore, BOOT_KEY_ITEM;"
                 " resolve_keystore().delete(BOOT_KEY_ITEM)"],
                capture_output=True, text=True, timeout=60,
                cwd=new_root / "agent-wallet", env=env,
            )
        shutil.rmtree(temp_home, ignore_errors=True)

    print(f"e2e_install_upgrade OK: backend={expect}, key identity preserved")


if __name__ == "__main__":
    main()
