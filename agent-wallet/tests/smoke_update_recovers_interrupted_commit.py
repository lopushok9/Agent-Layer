"""A same-version crash after release backup is recovered before the next install."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path


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


def _install(cli: Path, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
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
        timeout=300,
    )


def main() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    cli = repo_root / "bin" / "openclaw-agent-wallet.mjs"
    temp_root = Path(tempfile.mkdtemp(prefix="openclaw-recover-interrupted-commit-"))
    try:
        env = dict(os.environ)
        env.update(
            {
                "OPENCLAW_HOME": str(temp_root),
                "AGENT_WALLET_BOOT_KEY": "test-boot-key-interrupted-commit",
                "AGENT_WALLET_MASTER_KEY": "test-master-key-interrupted-commit",
                "AGENT_WALLET_APPROVAL_SECRET": "test-approval-interrupted-commit",
                "AGENT_WALLET_VERIFY_DISABLE": "1",
                "HERMES_HOME": str(temp_root / "hermes"),
                "CODEX_HOME": str(temp_root / "codex-home"),
                "AGENT_WALLET_CODEX_PLUGIN_ROOT": str(temp_root / "codex-plugins"),
                "AGENT_WALLET_CODEX_MARKETPLACE_PATH": str(temp_root / "marketplace.json"),
                "AGENT_WALLET_CLAUDE_CODE_MARKETPLACE_DIR": str(temp_root / "claude-marketplace"),
                "AGENT_WALLET_CLAUDE_CODE_CACHE_ROOT": str(temp_root / "claude-cache"),
            }
        )
        first = _install(cli, env)
        assert first.returncode == 0, first.stderr

        runtime_base = temp_root / "agent-wallet-runtime"
        current = runtime_base / "current"
        release = current.resolve()
        assert release.exists()

        interrupted = _install(
            cli,
            {**env, "AGENT_WALLET_TEST_EXIT_AFTER_RELEASE_RENAME": "1"},
        )
        assert interrupted.returncode == 86, interrupted.stderr
        assert current.is_symlink() and not current.exists()
        journal = json.loads((runtime_base / "update-journal.json").read_text(encoding="utf-8"))
        assert journal["state"] == "committing", journal
        assert not Path(journal["release_root"]).exists(), journal
        assert Path(journal["replaced_root"]).exists(), journal

        recovered = _install(cli, env)
        assert recovered.returncode == 0, recovered.stderr
        payload = _last_json(recovered.stderr)
        assert payload["recovery"] == {
            "attempted": True,
            "ok": True,
            "action": "restored_replaced_release",
        }, payload
        assert current.exists()
        assert current.resolve() == release
        final_journal = json.loads(
            (runtime_base / "update-journal.json").read_text(encoding="utf-8")
        )
        assert final_journal["state"] == "committed", final_journal

        print("smoke_update_recovers_interrupted_commit: ok")
    finally:
        shutil.rmtree(temp_root, ignore_errors=True)


if __name__ == "__main__":
    main()
