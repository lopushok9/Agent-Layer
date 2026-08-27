"""The connector lifecycle is available through a stable JSON CLI."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


def _run(package_root: Path, env: dict[str, str], *args: str, ok: bool = True):
    result = subprocess.run(
        [sys.executable, "-m", "agent_wallet.connector_cli", *args],
        cwd=package_root,
        env=env,
        capture_output=True,
        text=True,
    )
    if ok:
        assert result.returncode == 0, result.stderr
        return json.loads(result.stdout)
    assert result.returncode != 0, result.stdout
    return json.loads(result.stderr)


def main() -> None:
    package_root = Path(__file__).resolve().parents[1]
    temp_root = Path(tempfile.mkdtemp(prefix="agentlayer-connector-cli-"))
    try:
        manifest_path = temp_root / "manifest.json"
        manifest_path.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "id": "com.example.discovery",
                    "name": "Example Discovery",
                    "version": "1.0.0",
                    "publisher": {"id": "example", "name": "Example"},
                    "agentlayer": {"protocol_version": 1, "runtime_range": ">=0.1.101"},
                    "trust": "community_read_only",
                    "transport": {
                        "type": "https",
                        "url": "https://connector.example.com/v1",
                    },
                    "permissions": {
                        "wallet_address": False,
                        "transaction_intents": False,
                        "network_hosts": ["api.example.com"],
                    },
                    "tools": [
                        {
                            "name": "search",
                            "description": "Search public markets.",
                            "read_only": True,
                            "risk_level": "low",
                            "input_schema": {"type": "object"},
                            "output_schema": {"type": "object"},
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        env = dict(os.environ)
        env["OPENCLAW_HOME"] = str(temp_root / "home")
        env["PYTHONPATH"] = str(package_root)

        review = _run(package_root, env, "inspect", str(manifest_path))["review"]
        assert review["permissions"]["wallet_address"] is False
        assert review["tools"] == ["search"]

        unconfirmed = _run(
            package_root,
            env,
            "install",
            str(manifest_path),
            "--enable",
            ok=False,
        )
        assert "requires --yes" in unconfirmed["error"]
        assert _run(package_root, env, "list")["connectors"] == []

        installed = _run(
            package_root,
            env,
            "install",
            str(manifest_path),
            "--enable",
            "--yes",
        )
        assert installed["connector"]["enabled"] is True
        assert installed["review"] == review

        listed = _run(package_root, env, "list")
        assert [item["id"] for item in listed["connectors"]] == ["com.example.discovery"]

        tools = _run(package_root, env, "tools")
        assert [item["name"] for item in tools["tools"]] == [
            "connector__com_example_discovery__search"
        ]
        assert tools["tools"][0]["read_only"] is True

        doctor = _run(package_root, env, "doctor")
        assert doctor["ok"] is True
        assert doctor["checks"][0]["ok"] is True

        rejected = _run(
            package_root,
            env,
            "remove",
            "com.example.discovery",
            ok=False,
        )
        assert "requires --yes" in rejected["error"]

        _run(package_root, env, "disable", "com.example.discovery")
        enable_rejected = _run(
            package_root,
            env,
            "enable",
            "com.example.discovery",
            ok=False,
        )
        assert "requires --yes" in enable_rejected["error"]
        _run(package_root, env, "enable", "com.example.discovery", "--yes")
        _run(package_root, env, "disable", "com.example.discovery")
        removed = _run(
            package_root,
            env,
            "remove",
            "com.example.discovery",
            "--yes",
        )
        assert removed["removed"] is True
        assert _run(package_root, env, "list")["connectors"] == []

        print("smoke_connector_cli: ok")
    finally:
        shutil.rmtree(temp_root, ignore_errors=True)


if __name__ == "__main__":
    main()
