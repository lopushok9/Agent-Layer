"""Check that the Git marketplace installs a self-contained Codex MCP bridge."""

from __future__ import annotations

import json
import os
import shlex
import subprocess
import tempfile
from pathlib import Path


def main() -> None:
    root = Path(__file__).resolve().parents[2]
    marketplace = json.loads((root / ".agents/plugins/marketplace.json").read_text())
    assert marketplace["name"] == "agentlayer"
    plugin = marketplace["plugins"][0]
    assert plugin["name"] == "agent-wallet"
    assert plugin["source"]["source"] == "git-subdir"
    assert plugin["source"]["path"] == "./codex/plugins/agent-wallet"
    assert (root / plugin["source"]["path"] / ".codex-plugin/plugin.json").is_file()

    mcp = json.loads((root / "codex/plugins/agent-wallet/.mcp.json").read_text())
    command = mcp["mcpServers"]["agent-wallet"]["args"]
    assert command[0] == "-lc"

    with tempfile.TemporaryDirectory() as directory:
        tmp = Path(directory)
        home = tmp / "wallet-home"
        launcher = home / "agent-wallet-runtime/current/codex/plugins/agent-wallet/scripts/run_mcp.sh"
        fake_bin = tmp / "bin"
        fake_bin.mkdir()
        fake_npx = fake_bin / "npx"
        fake_npx.write_text(
            "#!/bin/sh\n"
            "printf '%s\\n' \"$*\" >> \"$OPENCLAW_HOME/npx-calls\"\n"
            "mkdir -p \"$(dirname \"$TEST_LAUNCHER\")\"\n"
            "printf '#!/bin/sh\\nprintf READY\\n' > \"$TEST_LAUNCHER\"\n"
            "printf 'installer output\\n'\n",
            encoding="utf-8",
        )
        fake_npx.chmod(0o755)
        home.mkdir()
        env = dict(os.environ)
        env.update(
            {
                "OPENCLAW_HOME": str(home),
                "TEST_LAUNCHER": str(launcher),
            }
        )
        # macOS login shells rebuild PATH, so put the fake npx first *inside*
        # the shell. This prevents the smoke test from contacting npm.
        isolated_command = ["-lc", f"PATH={shlex.quote(str(fake_bin))}:$PATH; {command[1]}"]

        first = subprocess.run(["sh", *isolated_command], env=env, text=True, capture_output=True, timeout=30)
        assert first.returncode == 0, first.stderr
        assert first.stdout == "READY", first.stdout
        assert "installer output" in first.stderr
        calls = (home / "npx-calls").read_text().splitlines()
        assert calls == ["--yes @agentlayer.tech/wallet@latest install --yes --runtime-only"]

        second = subprocess.run(["sh", *isolated_command], env=env, text=True, capture_output=True, timeout=30)
        assert second.returncode == 0, second.stderr
        assert second.stdout == "READY", second.stdout
        assert (home / "npx-calls").read_text().splitlines() == calls

    print("smoke_codex_git_marketplace: ok")


if __name__ == "__main__":
    main()
