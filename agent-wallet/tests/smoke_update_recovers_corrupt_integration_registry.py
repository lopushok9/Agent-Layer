"""A corrupt integration registry is preserved and cannot fail runtime update."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path


def main() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    cli = repo_root / "bin" / "openclaw-agent-wallet.mjs"
    version = json.loads((repo_root / "package.json").read_text(encoding="utf-8"))["version"]
    temp_root = Path(tempfile.mkdtemp(prefix="openclaw-corrupt-integration-registry-"))
    try:
        runtime_base = temp_root / "agent-wallet-runtime"
        old_release = runtime_base / "releases" / "0.0.9"
        old_release.mkdir(parents=True)
        (runtime_base / "current").symlink_to(old_release)
        registry_path = runtime_base / "integrations.json"
        corrupt_contents = '{"schema_version":1,"integrations":'
        registry_path.write_text(corrupt_contents, encoding="utf-8")

        env = dict(os.environ)
        env.update(
            {
                "OPENCLAW_HOME": str(temp_root),
                "OPENCLAW_AGENT_WALLET_UPDATE_CLI_PATH": str(cli),
                "AGENT_WALLET_BOOT_KEY": "test-corrupt-registry-boot-key",
                "AGENT_WALLET_MASTER_KEY": "test-corrupt-registry-master-key",
                "AGENT_WALLET_APPROVAL_SECRET": "test-corrupt-registry-approval",
                "AGENT_WALLET_VERIFY_DISABLE": "1",
                "HERMES_HOME": str(temp_root / "hermes"),
                "CODEX_HOME": str(temp_root / "codex-home"),
                "AGENT_WALLET_CODEX_PLUGIN_ROOT": str(temp_root / "codex-plugins"),
                "AGENT_WALLET_CODEX_MARKETPLACE_PATH": str(temp_root / "marketplace.json"),
                "AGENT_WALLET_CLAUDE_CODE_MARKETPLACE_DIR": str(temp_root / "claude-marketplace"),
                "AGENT_WALLET_CLAUDE_CODE_CACHE_ROOT": str(temp_root / "claude-cache"),
            }
        )

        before = subprocess.run(
            ["node", str(cli), "status"], capture_output=True, text=True, check=True, env=env
        )
        before_status = json.loads(before.stdout)["framework_integrations"]
        assert before_status["registry_ok"] is False, before_status
        assert before_status["in_sync"] is False, before_status
        assert registry_path.read_text(encoding="utf-8") == corrupt_contents

        update = subprocess.run(
            [
                "node",
                str(cli),
                "update",
                "--yes",
                "--backend",
                "none",
                "--skip-python-setup",
                "--skip-node-setup",
            ],
            capture_output=True,
            text=True,
            check=True,
            env=env,
            timeout=300,
        )
        payload = json.loads(update.stdout)
        assert payload["active_version"] == version, payload
        assert (runtime_base / "current").resolve() == (
            runtime_base / "releases" / version
        ).resolve()

        backups = list(runtime_base.glob("integrations.json.corrupt-*"))
        assert len(backups) == 1, backups
        assert backups[0].read_text(encoding="utf-8") == corrupt_contents
        recovered = json.loads(registry_path.read_text(encoding="utf-8"))
        assert set(recovered["integrations"]) == {"openclaw"}, recovered
        assert recovered["recovered_corrupt_registry"] == backups[0].name, recovered

        after = subprocess.run(
            ["node", str(cli), "status"], capture_output=True, text=True, check=True, env=env
        )
        after_status = json.loads(after.stdout)["framework_integrations"]
        assert after_status["registry_ok"] is True, after_status
        assert after_status["recovered_corrupt_registry"] == backups[0].name, after_status

        print("smoke_update_recovers_corrupt_integration_registry: ok")
    finally:
        shutil.rmtree(temp_root, ignore_errors=True)


if __name__ == "__main__":
    main()
