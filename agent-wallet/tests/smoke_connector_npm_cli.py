"""The public wallet CLI forwards connector lifecycle commands to Python."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


def _run(cli: Path, env: dict[str, str], *args: str) -> dict:
    result = subprocess.run(
        ["node", str(cli), "connectors", *args],
        env=env,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def main() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    cli = repo_root / "bin" / "openclaw-agent-wallet.mjs"
    temp_root = Path(tempfile.mkdtemp(prefix="agentlayer-connector-npm-cli-"))
    try:
        manifest_path = temp_root / "manifest.json"
        manifest_path.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "id": "com.example.npm",
                    "name": "NPM CLI Example",
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
        env["AGENT_WALLET_PYTHON"] = sys.executable

        installed = _run(cli, env, "install", str(manifest_path), "--enable")
        assert installed["connector"]["enabled"] is True
        listed = _run(cli, env, "list")
        assert listed["connectors"][0]["id"] == "com.example.npm"
        doctor = _run(cli, env, "doctor")
        assert doctor["ok"] is True

        print("smoke_connector_npm_cli: ok")
    finally:
        shutil.rmtree(temp_root, ignore_errors=True)


if __name__ == "__main__":
    main()

