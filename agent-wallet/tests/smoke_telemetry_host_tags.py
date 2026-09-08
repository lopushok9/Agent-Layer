"""Smoke coverage for host attribution in Codex and OpenClaw bridges."""

from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
CODEX_SERVER = REPO_ROOT / "codex" / "plugins" / "agent-wallet" / "server.py"
OPENCLAW_EXTENSION = REPO_ROOT / ".openclaw" / "extensions" / "agent-wallet" / "index.ts"


def _load_codex_server():
    spec = importlib.util.spec_from_file_location("telemetry_host_tags_codex_server", CODEX_SERVER)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def main() -> None:
    original_host = os.environ.get("AGENT_WALLET_HOST")
    try:
        os.environ.pop("AGENT_WALLET_HOST", None)
        server = _load_codex_server()
        assert server._cli_env(Path("/tmp/agent-wallet"))["AGENT_WALLET_HOST"] == "codex"
        os.environ["AGENT_WALLET_HOST"] = "mcp"
        assert server._cli_env(Path("/tmp/agent-wallet"))["AGENT_WALLET_HOST"] == "mcp"
    finally:
        if original_host is None:
            os.environ.pop("AGENT_WALLET_HOST", None)
        else:
            os.environ["AGENT_WALLET_HOST"] = original_host

    extension = OPENCLAW_EXTENSION.read_text(encoding="utf-8")
    assert 'env.AGENT_WALLET_HOST = env.AGENT_WALLET_HOST || "openclaw";' in extension
    print("smoke_telemetry_host_tags: ok")


if __name__ == "__main__":
    main()
