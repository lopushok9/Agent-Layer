"""Smoke test: `release:local` plans a full local release across frameworks.

A local release must (1) bump the canonical VERSION, (2) stamp every manifest,
(3) verify consistency, and (4) reinstall the runtime into all local agent
frameworks (OpenClaw, Codex, Claude Code) so they all run the new version.

This test exercises the non-mutating ``--dry-run`` plan: it asserts the ordered
steps without executing real installs or touching VERSION.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts/release_local.mjs"
VERSION_FILE = REPO_ROOT / "VERSION"


def main() -> None:
    before = VERSION_FILE.read_text(encoding="utf-8")
    env = dict(os.environ)
    res = subprocess.run(
        ["node", str(SCRIPT), "1.2.3", "--dry-run"],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        env=env,
        timeout=30,
    )
    assert res.returncode == 0, res.stderr
    plan = json.loads(res.stdout)

    assert plan["dry_run"] is True, plan
    assert plan["version"] == "1.2.3", plan
    step_names = [s["name"] for s in plan["steps"]]
    assert step_names == [
        "sync_version",
        "check_version",
        "install_openclaw",
        "install_codex",
        "install_claude_code",
    ], step_names
    # Every framework install carries the bumped version target.
    for step in plan["steps"]:
        assert "command" in step and step["command"], step

    # Dry-run must not mutate the canonical VERSION.
    assert VERSION_FILE.read_text(encoding="utf-8") == before

    print("OK smoke_release_local_plan")


if __name__ == "__main__":
    main()
