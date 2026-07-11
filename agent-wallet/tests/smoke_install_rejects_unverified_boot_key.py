"""A pre-resolver runtime cannot carry a stale explicit key through staged commit."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def _last_json(text: str) -> dict:
    depth = 0
    start = None
    payloads: list[dict] = []
    for index, char in enumerate(text):
        if char == "{":
            if depth == 0:
                start = index
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0 and start is not None:
                try:
                    payloads.append(json.loads(text[start : index + 1]))
                except json.JSONDecodeError:
                    pass
                start = None
    if not payloads:
        raise AssertionError(f"No JSON object found in: {text!r}")
    return payloads[-1]


def main() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    cli = repo_root / "bin" / "openclaw-agent-wallet.mjs"
    temp_root = Path(tempfile.mkdtemp(prefix="openclaw-reject-unverified-boot-key-"))
    try:
        runtime_base = temp_root / "agent-wallet-runtime"
        old_release = runtime_base / "releases" / "0.1.53"
        old_package = old_release / "agent-wallet" / "agent_wallet"
        old_package.mkdir(parents=True)
        (old_package / "__init__.py").write_text("", encoding="utf-8")
        (old_package / "config.py").write_text("# pre-resolver runtime\n", encoding="utf-8")
        runtime_bin = old_release / "agent-wallet" / ".runtime-venv" / "bin"
        runtime_bin.mkdir(parents=True)
        runtime_python = runtime_bin / "python"
        runtime_python.write_text(f'#!/bin/sh\nexec "{sys.executable}" "$@"\n', encoding="utf-8")
        runtime_python.chmod(0o755)
        (runtime_base / "current").symlink_to(old_release)

        env = dict(os.environ)
        env.update(
            {
                "OPENCLAW_HOME": str(temp_root),
                "AGENT_WALLET_BOOT_KEY": "stale-explicit-key",
                "AGENT_WALLET_KEYSTORE_BACKEND": "plaintext",
                "AGENT_WALLET_PYTHON": sys.executable,
                "AGENT_WALLET_VERIFY_DISABLE": "1",
                "HERMES_HOME": str(temp_root / "hermes"),
                "CODEX_HOME": str(temp_root / "codex-home"),
                "AGENT_WALLET_CODEX_PLUGIN_ROOT": str(temp_root / "codex-plugins"),
                "AGENT_WALLET_CODEX_MARKETPLACE_PATH": str(temp_root / "marketplace.json"),
                "AGENT_WALLET_CLAUDE_CODE_MARKETPLACE_DIR": str(temp_root / "claude-marketplace"),
                "AGENT_WALLET_CLAUDE_CODE_CACHE_ROOT": str(temp_root / "claude-cache"),
            }
        )

        os.environ.update(
            {
                "OPENCLAW_HOME": str(temp_root),
                "AGENT_WALLET_KEYSTORE_BACKEND": "plaintext",
            }
        )
        from agent_wallet.keystore import BOOT_KEY_ITEM, resolve_keystore
        from agent_wallet.sealed_keys import seal_keys

        correct_key = "correct-existing-key"
        seal_keys(correct_key, {"master_key": "master", "approval_secret": "approval"})
        store = resolve_keystore()
        store.set(BOOT_KEY_ITEM, correct_key)

        result = subprocess.run(
            [
                "node",
                str(cli),
                "install",
                "--yes",
                "--backend",
                "none",
                "--skip-python-setup",
                "--skip-node-setup",
            ],
            capture_output=True,
            text=True,
            env=env,
        )
        assert result.returncode != 0, result.stderr
        payload = _last_json(result.stderr)
        assert payload["category"] == "boot_key_rejected", payload
        assert payload["switched_current"] is False, payload
        assert (runtime_base / "current").resolve() == old_release.resolve()
        assert store.get(BOOT_KEY_ITEM) == correct_key
        assert "stale-explicit-key" not in result.stderr

        print("smoke_install_rejects_unverified_boot_key: ok")
    finally:
        shutil.rmtree(temp_root, ignore_errors=True)


if __name__ == "__main__":
    main()
