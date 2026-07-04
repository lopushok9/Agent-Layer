"""Install-time keystore bridge — the exact Python CLI entrypoints the Node
installer shells out to during runInstall.

The Node installer (bin/openclaw-agent-wallet.mjs) provisions the boot key by
spawning the runtime Python:
  - provision:  python -m agent_wallet.openclaw_cli boot-key-import --key-stdin
  - read-back:  python -c "... read_boot_key_from_keystore() ..."
  - recovery:   python -m agent_wallet.openclaw_cli boot-key-export

This drives those exact subprocess calls (not in-process) so OS-specific issues
— Windows stdin encoding, DPAPI, CLI arg parsing — are actually exercised.
Uses a throwaway keystore service so no real boot key is touched.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

PKG_DIR = str(Path(__file__).resolve().parents[1])  # the agent-wallet dir (holds agent_wallet/)


def main() -> None:
    temp_home = Path(tempfile.mkdtemp(prefix="openclaw-install-bridge-"))
    env = dict(os.environ)
    env["OPENCLAW_HOME"] = str(temp_home)
    env["AGENT_WALLET_KEYSTORE_SERVICE"] = "ai.agentlayer.wallet.bridgetest"
    for var in ("AGENT_WALLET_BOOT_KEY", "AGENT_WALLET_BOOT_KEY_FILE", "AGENT_WALLET_KEYSTORE_BACKEND"):
        env.pop(var, None)

    expect = env.get("AGENT_WALLET_EXPECT_BACKEND", "").strip()
    key = "bridge-boot-key-" + "z9" * 16  # 48 chars

    def run(args: list[str], *, input_text: str | None = None) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, *args],
            input=input_text,
            capture_output=True,
            text=True,
            env=env,
            cwd=PKG_DIR,
        )

    try:
        # 1. provision — what Node's provisionBootKeyToKeystore() runs.
        r = run(["-m", "agent_wallet.openclaw_cli", "boot-key-import", "--key-stdin"], input_text=key)
        assert r.returncode == 0, f"boot-key-import failed rc={r.returncode}: {r.stderr}"
        status = json.loads(r.stdout)
        assert status.get("imported") is True, status
        print("  provisioned via backend:", status.get("backend"))
        if expect:
            assert status.get("backend") == expect, f"expected {expect!r}, got {status.get('backend')!r}"

        # 2. read-back — what Node's readBootKeyFromKeystore() runs.
        r = run(["-c", "from agent_wallet.config import read_boot_key_from_keystore as f; print(f())"])
        assert r.returncode == 0, f"read-back failed: {r.stderr}"
        assert r.stdout.strip() == key, f"keystore read mismatch: {r.stdout.strip()!r}"

        # 3. export — the user-facing recovery command.
        r = run(["-m", "agent_wallet.openclaw_cli", "boot-key-export"])
        assert r.returncode == 0, f"boot-key-export failed: {r.stderr}"
        assert json.loads(r.stdout).get("boot_key") == key, "export returned the wrong key"
    finally:
        run(["-c", "from agent_wallet.keystore import resolve_keystore, BOOT_KEY_ITEM; resolve_keystore().delete(BOOT_KEY_ITEM)"])
        shutil.rmtree(temp_home, ignore_errors=True)

    print("smoke_install_keystore_bridge OK")


if __name__ == "__main__":
    main()
