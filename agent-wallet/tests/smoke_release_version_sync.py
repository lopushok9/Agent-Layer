"""Smoke test: check_release_version.mjs enforces __version__ sync.

The agent-wallet update notice compares the installed agent_wallet.__version__
against the npm-published version, so a release that bumps package.json /
pyproject.toml but forgets agent_wallet/__init__.py would nag users forever.
The release guard must catch that mismatch.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts/check_release_version.mjs"
TMP = Path("/tmp/openclaw-release-version-sync")


def _stage(pkg: str, py: str, init: str) -> None:
    if TMP.exists():
        shutil.rmtree(TMP)
    (TMP / "agent-wallet/agent_wallet").mkdir(parents=True, exist_ok=True)
    (TMP / "package.json").write_text(f'{{"version": "{pkg}"}}', encoding="utf-8")
    (TMP / "agent-wallet/pyproject.toml").write_text(
        f'[project]\nversion = "{py}"\n', encoding="utf-8"
    )
    (TMP / "agent-wallet/agent_wallet/__init__.py").write_text(
        f'__version__ = "{init}"\n', encoding="utf-8"
    )


def _run() -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env.pop("GITHUB_REF_NAME", None)
    env.pop("GITHUB_OUTPUT", None)
    return subprocess.run(
        ["node", str(SCRIPT)], cwd=str(TMP), capture_output=True, text=True, env=env, timeout=30
    )


def main() -> None:
    try:
        # All three aligned -> exit 0.
        _stage("0.1.40", "0.1.40", "0.1.40")
        res = _run()
        assert res.returncode == 0, res.stderr
        assert "release_version=0.1.40" in res.stdout, res.stdout

        # __init__.py drifted -> exit 1.
        _stage("0.1.40", "0.1.40", "0.1.39")
        res = _run()
        assert res.returncode == 1, res.stdout
        assert "__init__" in res.stderr, res.stderr

        print("OK smoke_release_version_sync")
    finally:
        shutil.rmtree(TMP, ignore_errors=True)


if __name__ == "__main__":
    main()
