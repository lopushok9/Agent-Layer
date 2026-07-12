"""Status and doctor report interrupted updates without mutating recovery state."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path


def _run(cli: Path, command: str, env: dict[str, str]) -> dict:
    result = subprocess.run(
        ["node", str(cli), command], capture_output=True, text=True, env=env, timeout=60
    )
    return json.loads(result.stdout)


def main() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    cli = repo_root / "bin" / "openclaw-agent-wallet.mjs"
    temp_root = Path(tempfile.mkdtemp(prefix="openclaw-update-recovery-status-"))
    try:
        runtime_base = temp_root / "agent-wallet-runtime"
        releases = runtime_base / "releases"
        replaced = releases / "0.1.75-replaced"
        staging = releases / ".staging-0.1.75-test"
        replaced.mkdir(parents=True)
        staging.mkdir()
        release = releases / "0.1.75"
        (runtime_base / "current").symlink_to(release)
        journal_path = runtime_base / "update-journal.json"
        journal_path.write_text(
            json.dumps(
                {
                    "schema_version": 2,
                    "state": "committing",
                    "version": "0.1.75",
                    "staging_root": str(staging),
                    "release_root": str(release),
                    "replaced_root": str(replaced),
                }
            )
            + "\n",
            encoding="utf-8",
        )
        env = {**os.environ, "OPENCLAW_HOME": str(temp_root)}

        status = _run(cli, "status", env)
        assert status["schema_version"] == 1, status
        recovery = status["update_recovery"]
        assert recovery["state"] == "committing", recovery
        assert recovery["needs_recovery"] is True, recovery
        assert recovery["current_resolves"] is False, recovery

        doctor = _run(cli, "doctor", env)
        assert doctor["schema_version"] == 1, doctor
        check = next(item for item in doctor["checks"] if item["name"] == "update_recovery_state")
        assert check["needs_recovery"] is True, check
        assert check["fix"] == "wallet install --yes", check

        assert json.loads(journal_path.read_text(encoding="utf-8"))["state"] == "committing"
        assert replaced.exists() and staging.exists()

        print("smoke_update_recovery_status: ok")
    finally:
        shutil.rmtree(temp_root, ignore_errors=True)


if __name__ == "__main__":
    main()
