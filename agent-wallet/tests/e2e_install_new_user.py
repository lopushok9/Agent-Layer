"""Full new-user install acceptance: the real npx-style install into a clean home.

Drives the actual Node CLI (bin/openclaw-agent-wallet.mjs install --yes) with a
REAL Python venv setup — the exact path a first-time user takes — then asserts
the boot-key security contract end to end:

  1. install succeeds and activates the release (current symlink);
  2. the release .env contains NO plaintext AGENT_WALLET_BOOT_KEY;
  3. the generated boot key lives in the OS keystore (expected backend per OS)
     and round-trips through the runtime venv python and boot-key-export;
  4. wallet material sealed with that key through the installed runtime unseals
     again with NO secret in the environment — the full new-user arc
     (install -> create wallet -> restart with nothing but the keystore).

Slow (real venv + pip install), so it runs from install-e2e.yml, not the
per-push smoke loops. Node project setup is skipped: the wdk node runtimes have
their own coverage and are irrelevant to the boot-key contract.

Keystore isolation: AGENT_WALLET_KEYSTORE_SERVICE points at a throwaway service
so a local run never touches the machine's real boot-key slot. The driver is
stdlib-only; every agent_wallet call goes through the installed release's venv.
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
TEST_SERVICE = "ai.agentlayer.wallet.e2etest"

SEAL_SCRIPT = """
import hashlib, json
from agent_wallet.bootstrap import generate_solana_wallet_material
from agent_wallet.config import read_boot_key_from_keystore
from agent_wallet.sealed_keys import seal_keys

key = read_boot_key_from_keystore()
assert key, "boot key missing from keystore at seal time"
material = generate_solana_wallet_material()
seal_keys(key, {
    "master_key": "e2e-master-secret",
    "approval_secret": "e2e-approval-secret",
    "private_key": material["secret_material"],
})
print(json.dumps({"material_sha": hashlib.sha256(material["secret_material"].encode()).hexdigest()}))
"""

UNSEAL_SCRIPT = """
import hashlib, json
from agent_wallet.config import (
    resolve_approval_secret,
    resolve_solana_private_key,
    resolve_wallet_master_key,
)

print(json.dumps({
    "master": resolve_wallet_master_key(),
    "approval": resolve_approval_secret(),
    "material_sha": hashlib.sha256(resolve_solana_private_key().encode()).hexdigest(),
}))
"""


def last_json_object(text: str) -> dict:
    """Parse the trailing pretty-printed JSON payload out of mixed install output."""
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
    temp_home = Path(tempfile.mkdtemp(prefix="openclaw-e2e-new-user-"))
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
    runtime_root = runtime_base / "releases" / version
    venv_python: Path | None = None

    def run_py(code: str, *, extra_env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
        assert venv_python is not None
        py_env = dict(env)
        if extra_env:
            py_env.update(extra_env)
        return subprocess.run(
            [str(venv_python), "-c", code],
            capture_output=True, text=True, timeout=120,
            cwd=runtime_root / "agent-wallet", env=py_env,
        )

    try:
        # The full first-time install: real venv, real pip, verify enabled.
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
            f"install failed rc={install.returncode}\nstdout:\n{install.stdout[-3000:]}\n"
            f"stderr:\n{install.stderr[-3000:]}"
        )
        payload = last_json_object(install.stdout)
        assert payload.get("ok") is True, payload
        assert (runtime_base / "current").exists(), "current runtime pointer missing"
        assert (runtime_base / "current").resolve() == runtime_root.resolve()
        venv_python = resolve_venv_python(runtime_root)

        # Core contract: no plaintext boot key in the release .env.
        release_env = runtime_root / "agent-wallet" / ".env"
        if release_env.exists():
            content = release_env.read_text(encoding="utf-8")
            assert "AGENT_WALLET_BOOT_KEY=" not in content, (
                f"plaintext boot key leaked into {release_env}:\n{content}"
            )

        # The generated key must live in the expected OS keystore backend...
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
        boot_key = info["key"]
        assert boot_key, "boot key missing from keystore after install"

        # ...and be recoverable through the user-facing export command.
        export = subprocess.run(
            [str(venv_python), "-m", "agent_wallet.openclaw_cli", "boot-key-export"],
            capture_output=True, text=True, timeout=120,
            cwd=runtime_root / "agent-wallet", env=env,
        )
        assert export.returncode == 0, export.stderr
        assert json.loads(export.stdout)["boot_key"] == boot_key, "boot-key-export mismatch"

        # Raw OS-level proof on macOS: the key is really in the Keychain.
        if expect == "macos-keychain":
            sec = subprocess.run(
                ["/usr/bin/security", "find-generic-password",
                 "-s", TEST_SERVICE, "-a", "boot_key", "-w"],
                capture_output=True, text=True, timeout=30,
            )
            assert sec.returncode == 0, sec.stderr
            assert sec.stdout.strip() == boot_key, "Keychain item does not match runtime key"

        # New-user arc: create wallet material and seal it via the installed
        # runtime, then unseal in a fresh process with NO secret in the env —
        # only the keystore connects the two.
        sealed = run_py(SEAL_SCRIPT)
        assert sealed.returncode == 0, sealed.stderr
        material_sha = json.loads(sealed.stdout)["material_sha"]
        assert (temp_home / "sealed_keys.json").exists(), "sealed_keys.json not written"

        unsealed = run_py(UNSEAL_SCRIPT)
        assert unsealed.returncode == 0, unsealed.stderr
        secrets = json.loads(unsealed.stdout)
        assert secrets["master"] == "e2e-master-secret", secrets
        assert secrets["approval"] == "e2e-approval-secret", secrets
        assert secrets["material_sha"] == material_sha, "wallet material corrupted through seal/unseal"
    finally:
        if venv_python is not None:
            subprocess.run(
                [str(venv_python), "-c",
                 "from agent_wallet.keystore import resolve_keystore, BOOT_KEY_ITEM;"
                 " resolve_keystore().delete(BOOT_KEY_ITEM)"],
                capture_output=True, text=True, timeout=60,
                cwd=runtime_root / "agent-wallet", env=env,
            )
        shutil.rmtree(temp_home, ignore_errors=True)

    print(f"e2e_install_new_user OK: backend={expect}")


if __name__ == "__main__":
    main()
