"""Smoke test: single source of truth for the project version.

A root VERSION file is canonical. ``scripts/sync_version.mjs`` stamps it into all
derived manifests across every framework (npm installer, Python package, OpenClaw
extension, Codex/Claude Code/Hermes plugins, wdk packages).
``scripts/check_release_version.mjs`` fails when any manifest drifts from VERSION
or from a ``v*`` release tag, and emits the npm dist-tag for publishing.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SYNC = REPO_ROOT / "scripts/sync_version.mjs"
CHECK = REPO_ROOT / "scripts/check_release_version.mjs"
TMP = Path("/tmp/openclaw-version-consistency")

# (relative path, file body template with {v} placeholder, kind label)
MANIFESTS = {
    "package.json": '{{"name": "root", "version": "{v}"}}\n',
    "agent-wallet/pyproject.toml": '[project]\nname = "x"\nversion = "{v}"\n',
    "agent-wallet/agent_wallet/__init__.py": '"""pkg."""\n__version__ = "{v}"\n',
    ".openclaw/extensions/agent-wallet/package.json": '{{"name": "ext", "version": "{v}"}}\n',
    "agent-wallet/openclaw.plugin.json": '{{"id": "agent-wallet", "version": "{v}"}}\n',
    ".openclaw/extensions/agent-wallet/openclaw.plugin.json": '{{"id": "aw", "version": "{v}"}}\n',
    "codex/plugins/agent-wallet/.codex-plugin/plugin.json": '{{"name": "aw", "version": "{v}"}}\n',
    "claude-code/plugins/agent-wallet/.claude-plugin/plugin.json": '{{"name": "aw", "version": "{v}"}}\n',
    "hermes/plugins/agent_wallet/plugin.yaml": "name: agent-wallet\nversion: {v}\n",
    "wdk-btc-wallet/package.json": '{{"name": "wdk-btc", "version": "{v}"}}\n',
    "wdk-evm-wallet/package.json": '{{"name": "wdk-evm", "version": "{v}"}}\n',
}


def _stage(canonical: str, manifest_version: str) -> None:
    if TMP.exists():
        shutil.rmtree(TMP)
    TMP.mkdir(parents=True, exist_ok=True)
    (TMP / "VERSION").write_text(canonical + "\n", encoding="utf-8")
    for rel, template in MANIFESTS.items():
        path = TMP / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(template.format(v=manifest_version), encoding="utf-8")


def _read(rel: str) -> str:
    return (TMP / rel).read_text(encoding="utf-8")


def _run(script: Path, ref: str | None = None) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env.pop("GITHUB_OUTPUT", None)
    if ref is None:
        env.pop("GITHUB_REF_NAME", None)
    else:
        env["GITHUB_REF_NAME"] = ref
    return subprocess.run(
        ["node", str(script)], cwd=str(TMP), capture_output=True, text=True, env=env, timeout=30
    )


def main() -> None:
    try:
        # sync stamps VERSION into every manifest.
        _stage(canonical="9.9.9", manifest_version="0.0.0")
        res = _run(SYNC)
        assert res.returncode == 0, res.stderr
        for rel in MANIFESTS:
            assert "9.9.9" in _read(rel), f"{rel} not stamped: {_read(rel)!r}"
            assert "0.0.0" not in _read(rel), f"{rel} still stale: {_read(rel)!r}"

        # check passes when everything matches VERSION.
        res = _run(CHECK)
        assert res.returncode == 0, res.stderr
        assert "release_version=9.9.9" in res.stdout, res.stdout
        assert "npm_tag=latest" in res.stdout, res.stdout

        # check fails when a single manifest drifts.
        (TMP / "hermes/plugins/agent_wallet/plugin.yaml").write_text(
            "name: agent-wallet\nversion: 0.0.1\n", encoding="utf-8"
        )
        res = _run(CHECK)
        assert res.returncode == 1, res.stdout
        assert "plugin.yaml" in res.stderr, res.stderr

        # tag must match VERSION.
        _stage(canonical="9.9.9", manifest_version="0.0.0")
        _run(SYNC)
        res = _run(CHECK, ref="v9.9.8")
        assert res.returncode == 1, res.stdout
        assert "tag" in res.stderr.lower(), res.stderr
        res = _run(CHECK, ref="v9.9.9")
        assert res.returncode == 0, res.stderr

        # beta canonical -> beta dist-tag.
        _stage(canonical="9.9.9-beta.1", manifest_version="0.0.0")
        _run(SYNC)
        res = _run(CHECK, ref="v9.9.9-beta.1")
        assert res.returncode == 0, res.stderr
        assert "npm_tag=beta" in res.stdout, res.stdout

        print("OK smoke_version_consistency")
    finally:
        shutil.rmtree(TMP, ignore_errors=True)


if __name__ == "__main__":
    main()
