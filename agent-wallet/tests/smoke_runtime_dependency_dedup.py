"""Smoke test for shared Python and Node dependency reuse across runtime releases."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


def _extract_json_object(text: str) -> dict[str, object]:
    start = text.rfind("\n{")
    if start == -1:
        start = text.find("{")
    else:
        start += 1
    if start == -1:
        raise AssertionError(f"Could not find JSON payload in installer output:\n{text[-2000:]}")
    return json.loads(text[start:])


def _run_install(script: Path, runtime_root: Path, config_path: Path, env: dict[str, str]) -> dict[str, object]:
    completed = subprocess.run(
        [
            sys.executable,
            str(script),
            "--config-path",
            str(config_path),
            "--runtime-root",
            str(runtime_root),
            "--install-from-runtime",
            "--backend",
            "none",
        ],
        capture_output=True,
        text=True,
        check=True,
        env=env,
    )
    return _extract_json_object(completed.stdout)


def main() -> None:
    temp_root = Path(tempfile.mkdtemp(prefix="openclaw-runtime-dependency-dedup-smoke-"))

    repo_root = Path(__file__).resolve().parents[2]
    script = repo_root / "agent-wallet" / "scripts" / "install_agent_wallet.py"
    runtime_base = temp_root / "agent-wallet-runtime"
    release_a = runtime_base / "releases" / "test-a"
    release_b = runtime_base / "releases" / "test-b"
    config_path = temp_root / "openclaw.json"

    env = dict(os.environ)
    env["OPENCLAW_HOME"] = str(temp_root)

    payload_a = _run_install(script, release_a, config_path, env)
    payload_b = _run_install(script, release_b, config_path, env)

    python_link_a = release_a / "agent-wallet" / ".runtime-venv"
    python_link_b = release_b / "agent-wallet" / ".runtime-venv"
    assert python_link_a.is_symlink()
    assert python_link_b.is_symlink()
    assert python_link_a.resolve() == python_link_b.resolve()
    assert payload_a["python_runtime"]["shared"] is True
    assert payload_b["python_runtime"]["shared"] is True
    assert payload_a["python_runtime"]["fingerprint"] == payload_b["python_runtime"]["fingerprint"]

    node_projects = [
        release_a / "wdk-btc-wallet",
        release_a / "wdk-evm-wallet",
        release_a / "agent-wallet" / "scripts" / "flash-sdk-bridge",
    ]
    other_projects = [
        release_b / "wdk-btc-wallet",
        release_b / "wdk-evm-wallet",
        release_b / "agent-wallet" / "scripts" / "flash-sdk-bridge",
    ]
    for first, second in zip(node_projects, other_projects):
        first_modules = first / "node_modules"
        second_modules = second / "node_modules"
        assert first_modules.is_symlink()
        assert second_modules.is_symlink()
        assert first_modules.resolve() == second_modules.resolve()

    first_node_projects = payload_a["node_runtime"]["projects"]
    second_node_projects = payload_b["node_runtime"]["projects"]
    assert all(project["shared"] is True for project in first_node_projects)
    assert all(project["shared"] is True for project in second_node_projects)
    assert all(project["created"] is True for project in first_node_projects)
    assert all(project["created"] is False for project in second_node_projects)

    print("smoke_runtime_dependency_dedup: ok")


if __name__ == "__main__":
    main()
